package issues

import (
	"fmt"
	"time"

	"github.com/mb-89/SE/src/internal/index"
)

// Instance is the wiring's instance of Module, whose config the issue work reads.
const Instance = "issues"

// Module declares the issue work's config keys on the index, each with its
// constant as the built-in value: the retro's and the overhaul's cadence, the
// lease, the cap on a review's filed findings, and the cap on a box's
// follow-ups with the share of them the retro holds the fleet to.
var Module = index.Declare("issues", "The se issue work: the queue, its takes and leases, its reviews, and the cadences of retros and overhauls.",
	index.Config("retro-cadence", RetroCadence, "How many se issues close between two retros: at this many closed since the last retro closed, se issue pull --take starts an unattended one."),
	index.Config("overhaul-cadence", OverhaulCadence, "How many retros close between two overhauls: at this many closed since the last overhaul closed, se issue pull --take starts an unattended one; an overhaul reads the retro's last this many runs."),
	index.Config("lease", Lease, "How long a claimed leaf may go without a push to its branch before it is stuck; it is under the routine's 4-hour schedule."),
	index.Config("max-filed", MaxFiled, "How many non-blocking findings one review files as issues; the rest are counted, not filed."),
	index.Config("max-followups", MaxFollowups, "How many issues a box files with se issue new: they are queued, and its land, supersede or close files them; what is left beyond goes into them, or into one for a person."),
	index.Config("followup-share", FollowupShare, "The percent of the issues a box closed that may have filed a follow-up: above it, the retro finds the followups rule check broken."),
	index.Config("manifest-target", ManifestTarget, "issues.manifest/config/target: how long one manifest's leaves together should take, and how long a misc manifest takes new issues from its creation."),
	index.Config("paused", false, "fleet.box/config/paused: set on main, every box ends before its next pull, and se issue pull --take takes nothing."),
)

func init() { index.Register(Module) }

// Settings are Module's config values.
type Settings struct {
	RetroCadence, OverhaulCadence, MaxFiled, MaxFollowups, FollowupShare int
	Lease                                                                time.Duration
	// ManifestTarget is how long a manifest's leaves together should take;
	// Paused stops the fleet's takes.
	ManifestTarget time.Duration
	Paused         bool
}

// Builtin is Module's config as its built-in values give it.
func Builtin() Settings {
	return Settings{RetroCadence: RetroCadence, OverhaulCadence: OverhaulCadence, MaxFiled: MaxFiled, MaxFollowups: MaxFollowups, FollowupShare: FollowupShare, Lease: Lease, ManifestTarget: ManifestTarget}
}

// Configured answers the settings of Instance from the wiring se carries.
func Configured() (Settings, error) {
	w, err := index.Wired()
	if err != nil {
		return Settings{}, err
	}
	return From(w)
}

// From answers the settings of Instance as the wiring w gives them, each read
// through config/<key>. It starts an index of w's issues instances alone, so
// it needs no other module.
func From(w index.Wiring) (Settings, error) {
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
	var s Settings
	for key, into := range map[string]*int{"retro-cadence": &s.RetroCadence, "overhaul-cadence": &s.OverhaulCadence, "max-filed": &s.MaxFiled, "max-followups": &s.MaxFollowups, "followup-share": &s.FollowupShare} {
		if err := read(ix, key, into); err != nil {
			return Settings{}, err
		}
	}
	for key, into := range map[string]*time.Duration{"lease": &s.Lease, "manifest-target": &s.ManifestTarget} {
		if err := read(ix, key, into); err != nil {
			return Settings{}, err
		}
	}
	if err := read(ix, "paused", &s.Paused); err != nil {
		return Settings{}, err
	}
	return s, nil
}

// read reads Instance's config key into into.
func read[T any](ix *index.Index, key string, into *T) error {
	name := Instance + "/" + index.ConfigPrefix + key
	v, err := ix.Read(name)
	if err != nil {
		return err
	}
	t, ok := v.V.(T)
	if !ok {
		return fmt.Errorf("%s is no %T: %v", name, *into, v.V)
	}
	*into = t
	return nil
}

// config is the settings s runs under: its Config, else the built-in values.
func (s Source) config() Settings {
	if s.Config != nil {
		return *s.Config
	}
	return Builtin()
}
