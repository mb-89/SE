package http

import (
	"bytes"
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	nethttp "net/http"
	"strconv"
	"strings"
	"time"
)

// Real answers the network: loopback for the daemon, the routine's trigger
// through the environment's proxy.
func Real() Net {
	return wire{
		// The daemon answers on loopback alone, so its calls never go through a proxy.
		direct: &nethttp.Client{Transport: &nethttp.Transport{Proxy: nil}, Timeout: 2 * time.Second},
		out:    &nethttp.Client{Transport: &nethttp.Transport{Proxy: nethttp.ProxyFromEnvironment}, Timeout: 30 * time.Second},
	}
}

type wire struct{ direct, out *nethttp.Client }

func (w wire) Serve(ctx context.Context, token string, d Daemon) (string, <-chan error, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", nil, err
	}
	srv := &nethttp.Server{Handler: handler(token, d), ReadHeaderTimeout: 10 * time.Second}
	done := make(chan error, 1)
	served := make(chan error, 1)
	go func() { served <- srv.Serve(ln) }()
	go func() {
		select {
		case err := <-served:
			done <- err
		case <-ctx.Done():
			quit, stop := context.WithTimeout(context.Background(), 5*time.Second)
			defer stop()
			err := srv.Shutdown(quit)
			if s := <-served; !errors.Is(s, nethttp.ErrServerClosed) && err == nil {
				err = s
			}
			done <- err
		}
	}()
	return ln.Addr().String(), done, nil
}

// handler routes /health, /event, /value/<name>, /stale/<name> and /shutdown, each behind the token.
func handler(token string, d Daemon) nethttp.Handler {
	mux := nethttp.NewServeMux()
	mux.HandleFunc("GET /health", func(rw nethttp.ResponseWriter, _ *nethttp.Request) { answer(rw, d.Health()) })
	mux.HandleFunc("POST /event", func(rw nethttp.ResponseWriter, r *nethttp.Request) {
		var ev Event
		if err := json.NewDecoder(nethttp.MaxBytesReader(rw, r.Body, EventCap)).Decode(&ev); err != nil {
			nethttp.Error(rw, "bad event: "+err.Error(), StatusBadRequest)
			return
		}
		if err := d.Event(ev); err != nil {
			code := StatusInternal
			if errors.Is(err, ErrBad) {
				code = StatusBadRequest
			}
			nethttp.Error(rw, err.Error(), code)
			return
		}
		answer(rw, struct{}{})
	})
	mux.HandleFunc("GET /value/{name...}", func(rw nethttp.ResponseWriter, r *nethttp.Request) {
		v, err := d.Value(r.PathValue("name"))
		if err != nil {
			code := StatusInternal
			if errors.Is(err, ErrUnknown) {
				code = StatusNotFound
			}
			nethttp.Error(rw, err.Error(), code)
			return
		}
		answer(rw, v)
	})
	mux.HandleFunc("POST /stale/{name...}", func(rw nethttp.ResponseWriter, r *nethttp.Request) {
		if err := d.Stale(r.PathValue("name")); err != nil {
			code := StatusInternal
			if errors.Is(err, ErrUnknown) {
				code = StatusNotFound
			}
			nethttp.Error(rw, err.Error(), code)
			return
		}
		answer(rw, struct{}{})
	})
	mux.HandleFunc("POST /shutdown", func(rw nethttp.ResponseWriter, _ *nethttp.Request) {
		answer(rw, struct{}{})
		go d.Shutdown()
	})
	want := []byte("Bearer " + token)
	return nethttp.HandlerFunc(func(rw nethttp.ResponseWriter, r *nethttp.Request) {
		if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), want) != 1 {
			nethttp.Error(rw, "unauthorized", StatusUnauthorized)
			return
		}
		mux.ServeHTTP(rw, r)
	})
}

func answer(rw nethttp.ResponseWriter, v any) {
	rw.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(rw).Encode(v)
}

func (w wire) Health(address, token string) (Health, error) {
	var h Health
	err := w.call(address, token, nethttp.MethodGet, "/health", nil, &h)
	return h, err
}

func (w wire) Event(address, token string, ev Event) error {
	body, err := json.Marshal(ev)
	if err != nil {
		return err
	}
	return w.call(address, token, nethttp.MethodPost, "/event", body, nil)
}

func (w wire) Value(address, token, name string) (Value, error) {
	var v Value
	err := w.call(address, token, nethttp.MethodGet, "/value/"+name, nil, &v)
	return v, err
}

func (w wire) Stale(address, token, name string) error {
	return w.call(address, token, nethttp.MethodPost, "/stale/"+name, nil, nil)
}

func (w wire) Shutdown(address, token string) error {
	return w.call(address, token, nethttp.MethodPost, "/shutdown", nil, nil)
}

func (w wire) call(address, token, method, path string, body []byte, into any) error {
	req, err := nethttp.NewRequest(method, "http://"+address+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := w.direct.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != StatusOK {
		said, _ := io.ReadAll(io.LimitReader(resp.Body, BodyCap))
		return &StatusError{Path: path, Status: resp.StatusCode, Said: strings.TrimSpace(string(said))}
	}
	if into == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(into)
}

func (w wire) Fire(url, token string) (Answer, error) {
	req, err := nethttp.NewRequest(nethttp.MethodPost, url, strings.NewReader("{}"))
	if err != nil {
		return Answer{}, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("anthropic-beta", routineBeta)
	req.Header.Set("anthropic-version", routineVersion)
	req.Header.Set("Content-Type", "application/json")
	resp, err := w.out.Do(req)
	if err != nil {
		return Answer{}, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, BodyCap))
	return Answer{Status: resp.StatusCode, Body: body, RetryAfter: resp.Header.Get("Retry-After")}, nil
}

// RetryAt is when a refusal's Retry-After header, said at now, lets the
// caller try again: now plus its seconds, or its HTTP date. A header that is
// missing or malformed answers the zero time.
func RetryAt(now time.Time, header string) time.Time {
	header = strings.TrimSpace(header)
	if secs, err := strconv.Atoi(header); err == nil && secs >= 0 {
		return now.Add(time.Duration(secs) * time.Second)
	}
	if at, err := nethttp.ParseTime(header); err == nil {
		return at
	}
	return time.Time{}
}

// StatusText names a status code, as "429 Too Many Requests".
func StatusText(code int) string {
	return strings.TrimSpace(fmt.Sprintf("%d %s", code, nethttp.StatusText(code)))
}
