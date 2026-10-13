package daemon

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"time"
)

// ErrRunning says another daemon holds this workspace.
var ErrRunning = errors.New("a daemon already runs for this workspace")

// Options shape one daemon's life.
type Options struct {
	// Idle ends the daemon after this long without a post; zero keeps it running.
	Idle time.Duration
	// Ready, when set, receives the endpoint once daemon.json is published.
	Ready func(Endpoint)
	// TakeOver, when set, asks a running daemon to step down and keeps trying
	// for the workspace until this long has passed, so a daemon that is started
	// again in between is asked to step down too.
	TakeOver time.Duration
}

// Serve runs the workspace's daemon until ctx ends, /shutdown is posted, or it idles out.
func Serve(ctx context.Context, paths Paths, opts Options) error {
	if err := Prepare(paths); err != nil {
		return err
	}
	held, err := acquire(paths, opts.TakeOver)
	if err != nil {
		return err
	}
	defer held.Close()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return err
	}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	ep := Endpoint{
		PID:             os.Getpid(),
		Address:         ln.Addr().String(),
		Token:           randomHex(32),
		InstanceID:      randomHex(8),
		ProtocolVersion: ProtocolVersion,
		StartedAt:       time.Now().UTC(),
	}
	srv := NewServer(paths, ep.Token, ep.InstanceID, cancel)
	httpSrv := &http.Server{Handler: srv.Handler(), ReadHeaderTimeout: 10 * time.Second}
	if err := WriteEndpoint(paths.Endpoint(), ep); err != nil {
		ln.Close()
		return err
	}
	defer withdraw(paths, ep.InstanceID)
	if opts.Ready != nil {
		opts.Ready(ep)
	}

	served := make(chan error, 1)
	go func() { served <- httpSrv.Serve(ln) }()
	if opts.Idle > 0 {
		go idles(ctx, srv, opts.Idle, cancel)
	}
	select {
	case err := <-served:
		return err
	case <-ctx.Done():
	}
	quit, stop := context.WithTimeout(context.Background(), 5*time.Second)
	defer stop()
	return httpSrv.Shutdown(quit)
}

// acquire takes the lifetime lock, stepping a running daemon aside for up to takeOver.
func acquire(paths Paths, takeOver time.Duration) (*os.File, error) {
	deadline := time.Now().Add(takeOver)
	for {
		held, err := lock(paths.Lock())
		if !errors.Is(err, ErrRunning) || takeOver <= 0 || !time.Now().Before(deadline) {
			return held, err
		}
		Stop(paths, time.Until(deadline))
		time.Sleep(50 * time.Millisecond)
	}
}

func idles(ctx context.Context, srv *Server, idle time.Duration, cancel func()) {
	tick := time.NewTicker(min(idle/4, time.Minute))
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			if srv.Idle() >= idle {
				cancel()
				return
			}
		}
	}
}

// withdraw removes daemon.json while it still names this instance.
func withdraw(paths Paths, instance string) {
	if ep, err := ReadEndpoint(paths.Endpoint()); err == nil && ep.InstanceID == instance {
		os.Remove(paths.Endpoint())
	}
}

func randomHex(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(fmt.Sprintf("random: %v", err))
	}
	return hex.EncodeToString(b)
}
