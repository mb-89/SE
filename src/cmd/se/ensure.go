package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/disk"
	sehttp "github.com/mb-89/SE/src/internal/io/http"
	"github.com/mb-89/SE/src/internal/io/proc"

	"github.com/mb-89/SE/src/internal/daemon"
)

// A daemon found down is started again at most this often.
const restartEvery = time.Minute

// The longest an ensure waits for another one's start: a first start builds se.
const startingWait = 5 * time.Minute

// Ensured is what se ensure prints: where the daemon answers, or how long the
// plugin waits before it asks again, and why.
type Ensured struct {
	Address   string `json:"address,omitempty"`
	Token     string `json:"token,omitempty"`
	RetryInMs int64  `json:"retryInMs,omitempty"`
	Error     string `json:"error,omitempty"`
}

func init() {
	register(Command{
		Name:    "ensure",
		Usage:   "ensure",
		Group:   "Daemon",
		Summary: "find the daemon, or start it again at most once a minute",
		Details: "answer the daemon that runs for the workspace, wherever daemon.json says it moved. One found down is started again, one start at a time and at most once a minute; until then it answers how long to wait. Prints JSON; the plugin asks it whenever an event finds no daemon.",
		Run: func(c *Call) (Reply, error) {
			if err := c.Parse(c.Flags("ensure")); err != nil {
				return Reply{}, err
			}
			said, err := json.Marshal(ensure(c.Proc, c.Paths(), c.Clock, c.Net))
			return Reply{Text: string(said)}, err
		},
	})
}

// ensure answers the running daemon, or starts one where no start was tried
// within restartEvery.
func ensure(procs proc.Procs, p daemon.Paths, clk clock.Clock, net sehttp.Net) Ensured {
	if ep, ok := daemon.Healthy(p, net); ok {
		return Ensured{Address: ep.Address, Token: ep.Token}
	}
	held, err := starting(p, clk)
	if err != nil {
		return Ensured{RetryInMs: restartEvery.Milliseconds(), Error: err.Error()}
	}
	defer held.Close()
	// Another start may have answered while this one waited for the lock.
	if ep, ok := daemon.Healthy(p, net); ok {
		return Ensured{Address: ep.Address, Token: ep.Token}
	}
	if wait := restartEvery - clk.Now().Sub(tried(p)); wait > 0 {
		return Ensured{RetryInMs: wait.Milliseconds()}
	}
	ep, _, err := startsDaemon(procs, p, clk, net)
	if err != nil {
		return Ensured{RetryInMs: restartEvery.Milliseconds(), Error: err.Error()}
	}
	return Ensured{Address: ep.Address, Token: ep.Token}
}

// starting takes the workspace's start lock, which every start road holds,
// waiting by clk while another start holds it.
func starting(p daemon.Paths, clk clock.Clock) (io.Closer, error) {
	if err := daemon.Prepare(p); err != nil {
		return nil, err
	}
	deadline := clk.Now().Add(startingWait)
	for {
		held, err := p.Disk.Lock(p.Starting())
		if !errors.Is(err, disk.ErrLocked) {
			return held, err
		}
		if !clk.Now().Before(deadline) {
			return nil, fmt.Errorf("another start held %s for %s", p.Starting(), startingWait)
		}
		clk.Sleep(50 * time.Millisecond)
	}
}

// tries records that a start is tried now, which ensure waits out.
func tries(p daemon.Paths, clk clock.Clock) error {
	return p.Disk.WriteFile(p.Tried(), []byte(clk.Now().UTC().Format(time.RFC3339Nano)))
}

// tried is when a start was last tried, or the zero time where none was recorded.
func tried(p daemon.Paths) time.Time {
	data, err := p.Disk.ReadFile(p.Tried())
	if err != nil {
		return time.Time{}
	}
	at, err := time.Parse(time.RFC3339Nano, string(data))
	if err != nil {
		return time.Time{}
	}
	return at
}
