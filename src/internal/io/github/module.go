package github

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/clock"
)

// Snapshots is the output the keeper commits each snapshot it reads to.
var Snapshots = index.Output("snapshot", Snapshot{}, "GitHub's answers to the fleet's reads, as the daemon last read them.")

// Module is GitHub on the index: an I/O module whose daemon keeps a
// snapshot of the fleet's reads warm (Keeper), and whose config says how
// fresh the snapshot and the reads behind it are.
var Module = index.Declare("github", "GitHub, read and written through its REST API; the daemon keeps a snapshot of the fleet's reads warm.",
	index.IO(),
	Snapshots,
	index.Config("refresh", 2*time.Minute, "How often the daemon reads its snapshot of GitHub again; it reads it at once after se writes to GitHub, too."),
	index.Config("settle", 5*time.Minute, "How long after an issue last changed its dependency summary is trusted in place of reading its blocked-by links."),
)

func init() { index.Register(Module) }

// Settings are Module's config values.
type Settings struct {
	// Refresh is how often the snapshot is read again.
	Refresh time.Duration
	// Settle is how long after an issue last changed its dependency summary
	// is trusted.
	Settle time.Duration
}

// Configured answers Module's settings as the wiring se carries gives them.
func Configured() (Settings, error) {
	w, err := index.Wired()
	if err != nil {
		return Settings{}, err
	}
	own := index.Wiring{}
	for _, in := range w.Instances {
		if in.Module == Module.Name() {
			own.Instances = append(own.Instances, in)
		}
	}
	ix, err := index.Start(own, Module)
	if err != nil {
		return Settings{}, err
	}
	return settingsOf(ix)
}

// instanceOf names the instance of Module on ix; "" where there is none.
func instanceOf(ix *index.Index) string {
	for _, in := range ix.Catalog().Instances {
		if in.Module == Module.Name() {
			return in.Name
		}
	}
	return ""
}

func settingsOf(ix *index.Index) (Settings, error) {
	inst := instanceOf(ix)
	if inst == "" {
		return Settings{}, fmt.Errorf("the wiring names no instance of the %s module", Module.Name())
	}
	var s Settings
	for key, into := range map[string]*time.Duration{"refresh": &s.Refresh, "settle": &s.Settle} {
		v, err := ix.Read(inst + "/" + index.ConfigPrefix + key)
		if err != nil {
			return Settings{}, err
		}
		d, ok := v.V.(time.Duration)
		if !ok {
			return Settings{}, fmt.Errorf("%s/%s%s is %T, not a duration", inst, index.ConfigPrefix, key, v.V)
		}
		*into = d
	}
	return s, nil
}

// Keeper keeps the snapshot on the index warm while the daemon runs: it
// reads one at once, again every refresh, and at once whenever it is told
// the snapshot is stale (Stale), as se does after it writes to GitHub.
type Keeper struct {
	// Read reads a snapshot, with the module's settings.
	Read func(Settings) (Snapshot, error)
	// Clock is what the refresh is timed by.
	Clock clock.Clock
	// Log hears each read that failed; the snapshot before it stays.
	Log func(string)
	// Kept hears each snapshot committed, where set.
	Kept  func(Snapshot)
	stale chan struct{}
	mu    sync.Mutex
	name  string
}

// NewKeeper answers a keeper that reads with read, timed by clk.
func NewKeeper(read func(Settings) (Snapshot, error), clk clock.Clock, log func(string)) *Keeper {
	return &Keeper{Read: read, Clock: clk, Log: log, stale: make(chan struct{}, 1)}
}

// Keep keeps the snapshot of the Module instance on ix until ctx ends.
func (k *Keeper) Keep(ctx context.Context, ix *index.Index) {
	inst := instanceOf(ix)
	set, err := settingsOf(ix)
	if err != nil {
		k.log(err.Error())
		return
	}
	k.mu.Lock()
	k.name = inst + "/snapshot"
	k.mu.Unlock()
	for {
		// The refresh counts from when a read begins.
		next := k.Clock.After(set.Refresh)
		snap, err := k.Read(set)
		switch {
		case err != nil:
			k.log(fmt.Sprintf("reading the GitHub snapshot: %v", err))
		default:
			if err := ix.Commit(inst, Snapshots.Set(snap)); err != nil {
				k.log(fmt.Sprintf("keeping the GitHub snapshot: %v", err))
			} else if k.Kept != nil {
				k.Kept(snap)
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-k.stale:
		case <-next:
		}
	}
}

// Stale tells the keeper that name, its snapshot, no longer matches GitHub:
// it reads it again at once. It answers whether name is the keeper's.
func (k *Keeper) Stale(name string) bool {
	if name != k.Name() {
		return false
	}
	select {
	case k.stale <- struct{}{}:
	default:
	}
	return true
}

// Name is the snapshot's name on the index the keeper keeps; "" before it keeps one.
func (k *Keeper) Name() string {
	k.mu.Lock()
	defer k.mu.Unlock()
	return k.name
}

func (k *Keeper) log(s string) {
	if k.Log != nil {
		k.Log(s)
	}
}
