package daemon

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
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
	// Clock is the time the daemon stamps, idles and waits by.
	Clock clock.Clock
	// Net is the network the daemon answers on.
	Net sehttp.Net
}

// Serve runs the workspace's daemon until ctx ends, /shutdown is posted, or it idles out.
func Serve(ctx context.Context, paths Paths, opts Options) error {
	if err := Prepare(paths); err != nil {
		return err
	}
	held, err := acquire(paths, opts.TakeOver, opts.Clock, opts.Net)
	if err != nil {
		return err
	}
	defer held.Close()

	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	token, instance := randomHex(32), randomHex(8)
	srv := NewServer(paths, instance, cancel, opts.Clock)
	address, served, err := opts.Net.Serve(ctx, token, srv)
	if err != nil {
		return err
	}
	ep := Endpoint{
		PID:             os.Getpid(),
		Address:         address,
		Token:           token,
		InstanceID:      instance,
		ProtocolVersion: ProtocolVersion,
		StartedAt:       opts.Clock.Now().UTC(),
	}
	if err := WriteEndpoint(paths.Endpoint(), ep); err != nil {
		cancel()
		<-served
		return err
	}
	defer withdraw(paths, ep.InstanceID)
	if opts.Ready != nil {
		opts.Ready(ep)
	}
	if opts.Idle > 0 {
		go idles(ctx, srv, opts.Idle, cancel, opts.Clock)
	}
	// Serving ends once ctx does: by the caller, /shutdown or the idle clock.
	return <-served
}

// acquire takes the lifetime lock, stepping a running daemon aside for up to takeOver.
func acquire(paths Paths, takeOver time.Duration, clk clock.Clock, net sehttp.Net) (*os.File, error) {
	deadline := clk.Now().Add(takeOver)
	for {
		held, err := lock(paths.Lock())
		if !errors.Is(err, ErrRunning) || takeOver <= 0 || !clk.Now().Before(deadline) {
			return held, err
		}
		_ = Stop(paths, deadline.Sub(clk.Now()), clk, net)
		clk.Sleep(50 * time.Millisecond)
	}
}

func idles(ctx context.Context, srv *Server, idle time.Duration, cancel func(), clk clock.Clock) {
	every := min(idle/4, time.Minute)
	for {
		select {
		case <-ctx.Done():
			return
		case <-clk.After(every):
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
