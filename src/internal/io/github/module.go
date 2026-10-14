package github

import (
	"fmt"
	"time"

	"github.com/mb-89/SE/src/index"
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
)

// Module is GitHub on the index: its config says how se lives within
// GitHub's rate limits, which every box and session share through the
// owner's one token.
var Module = index.Declare("github", "GitHub, read and written through its REST API, within its rate limits.",
	index.IO(),
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
	var s Settings
	for key, into := range map[string]*time.Duration{"wait-ceiling": &s.Ceiling, "write-spacing": &s.Spacing} {
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
