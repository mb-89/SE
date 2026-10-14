package github

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/io/clock"
)

// The built-in values of Module's config.
const (
	// WaitCeiling is the longest se waits, all told, for GitHub's rate limit
	// to reset: GitHub's window is an hour.
	WaitCeiling = time.Hour
	// WriteSpacing is the least time between two writes: GitHub asks for a
	// second between requests that create content.
	WriteSpacing = time.Second
	// QuotaFloor is the share of the hour's requests, in percent, below
	// which se fleet check says the quota runs low.
	QuotaFloor = 20
	// Refresh is how often the daemon reads its snapshot again.
	Refresh = 2 * time.Minute
	// Settle is how long after an issue last changed its dependency summary
	// is trusted in place of its links.
	Settle = 5 * time.Minute
)

// Snapshots is the output the keeper commits each snapshot it reads to.
var Snapshots = index.Output("snapshot", Snapshot{}, "GitHub's answers to the fleet's reads, as the daemon last read them.")

// Module is GitHub on the index: its config says how se lives within
// GitHub's rate limits, which every box and session share through the
// owner's one token, and how fresh the daemon keeps its warm snapshot of the
// fleet's reads (Keeper) and the reads behind it.
var Module = index.Declare("github", "GitHub, read and written through its REST API, within its rate limits; the daemon keeps a snapshot of the fleet's reads warm.",
	index.IO(),
	Snapshots,
	index.Config("refresh", Refresh, "How often the daemon reads its snapshot of GitHub again; it reads it at once after se writes to GitHub, too."),
	index.Config("settle", Settle, "How long after an issue last changed its dependency summary is trusted in place of reading its blocked-by links."),
	index.Config("wait-ceiling", WaitCeiling, "The longest an se command waits, all told, for GitHub's rate limit to reset; a reset further off fails the request at once, saying when it comes."),
	index.Config("write-spacing", WriteSpacing, "The least time between two of an se command's writes to GitHub, which keeps a sweep of comments, issues and labels under GitHub's limit on creating content."),
	index.Config("quota-floor", QuotaFloor, "The share of the hour's GitHub requests, in percent, below which se fleet check says the quota runs low."),
)

func init() { index.Register(Module) }

// Settings are Module's config values.
type Settings struct {
	Limits
	// Floor is the share of the hour's requests, in percent, below which the
	// quota runs low.
	Floor int
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
	return From(w)
}

// From answers Module's settings as the wiring w gives them. It starts an
// index of w's github instance alone, so it needs no other module.
func From(w index.Wiring) (Settings, error) {
	own, inst := index.Wiring{}, ""
	for _, in := range w.Instances {
		if in.Module == Module.Name() {
			own.Instances, inst = append(own.Instances, in), in.Name
		}
	}
	if inst == "" {
		return Settings{}, fmt.Errorf("the wiring names no instance of the %s module", Module.Name())
	}
	ix, err := index.Start(own, Module)
	if err != nil {
		return Settings{}, err
	}
	return settingsOf(ix, inst)
}

// settingsOf reads Module's settings off the instance inst on ix.
func settingsOf(ix *index.Index, inst string) (Settings, error) {
	var s Settings
	for key, into := range map[string]*time.Duration{"wait-ceiling": &s.Ceiling, "write-spacing": &s.Spacing, "refresh": &s.Refresh, "settle": &s.Settle} {
		if err := read(ix, inst, key, into); err != nil {
			return Settings{}, err
		}
	}
	if err := read(ix, inst, "quota-floor", &s.Floor); err != nil {
		return Settings{}, err
	}
	return s, nil
}

// read reads the instance inst's config key into into.
func read[T any](ix *index.Index, inst, key string, into *T) error {
	name := inst + "/" + index.ConfigPrefix + key
	v, err := ix.Read(name)
	if err != nil {
		return err
	}
	t, ok := v.V.(T)
	if !ok {
		return fmt.Errorf("%s is %T, not a %T", name, v.V, *into)
	}
	*into = t
	return nil
}

// Low says, where r is known and below floor percent of its limit, how the
// quota runs low; "" where it does not.
func (r Rate) Low(floor int) string {
	if !r.Known || r.Limit <= 0 || r.Remaining*100 >= floor*r.Limit {
		return ""
	}
	return fmt.Sprintf("GitHub's quota runs low: %d of the hour's %d requests left, under the %d%% floor (github/config/quota-floor), until it resets at %s; the fleet shares it, so pace what can wait",
		r.Remaining, r.Limit, floor, r.Reset.UTC().Format("15:04 UTC"))
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
	if inst == "" {
		k.log(fmt.Sprintf("the wiring names no instance of the %s module", Module.Name()))
		return
	}
	set, err := settingsOf(ix, inst)
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
