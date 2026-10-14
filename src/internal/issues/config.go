package issues

import (
	"fmt"
	"strings"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/github"
	"github.com/mb-89/SE/src/modules/issues/stuck"
)

// Instance is the wiring's instance of Module, whose config the issue work reads.
const Instance = "issues"

// Module declares the issue work's config keys on the index, each with its
// constant as the built-in value: the retro's and the overhaul's cadence, the
// cap on a review's filed findings. The lease is issues/stuck's.
var Module = index.Declare("issues", "The se issue work: the queue, its takes, its reviews, and the cadences of retros and overhauls.",
	index.Config("retro-cadence", RetroCadence, "How many se issues close between two retros: at this many closed since the last retro closed, se issue pull --take starts an unattended one."),
	index.Config("overhaul-cadence", OverhaulCadence, "How many retros close between two overhauls: at this many closed since the last overhaul closed, se issue pull --take starts an unattended one; an overhaul reads the retro's last this many runs."),
	index.Config("max-filed", MaxFiled, "How many non-blocking findings one review files as issues; the rest are counted, not filed."),
	index.Config("manifest-target", ManifestTarget, "issues.manifest/config/target: how long one manifest's leaves together should take, and how long a misc manifest takes new issues from its creation."),
	index.Config("paused", false, "fleet.box/config/paused: set on main, every box ends before its next pull, and se issue pull --take takes nothing."),
)

func init() { index.Register(Module) }

// Settings are Module's config values.
type Settings struct {
	RetroCadence, OverhaulCadence, MaxFiled int
	Lease                                   time.Duration
	// ManifestTarget is how long a manifest's leaves together should take;
	// Paused stops the fleet's takes.
	ManifestTarget time.Duration
	Paused         bool
}

// Builtin is Module's config as its built-in values give it.
func Builtin() Settings {
	return Settings{RetroCadence: RetroCadence, OverhaulCadence: OverhaulCadence, MaxFiled: MaxFiled, Lease: Lease, ManifestTarget: ManifestTarget}
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
// through config/<key>, and the lease of issues/stuck's instance. It starts an
// index of w's instances of the two modules alone, with the I/O modules their
// request ports are wired to, handed no outside thing, since a config read
// asks nothing.
func From(w index.Wiring) (Settings, error) {
	mods := []*index.Module{Module, stuck.Module, github.Module(nil), git.Module(nil, "")}
	own, keep, stuckAt := index.Wiring{}, map[string]bool{}, ""
	for _, in := range w.Instances {
		if in.Module == stuck.Module.Name() {
			stuckAt = in.Name
		}
		if in.Module == Module.Name() || in.Module == stuck.Module.Name() {
			keep[in.Name] = true
		}
	}
	for _, wire := range w.Wires {
		inst, _, _ := strings.Cut(wire.Port, ".")
		to, _, verb := strings.Cut(wire.To, ".")
		if keep[inst] && verb {
			own.Wires = append(own.Wires, wire)
			keep[to] = true
		}
	}
	for _, in := range w.Instances {
		if keep[in.Name] {
			own.Instances = append(own.Instances, in)
		}
	}
	ix, err := index.Start(own, mods...)
	if err != nil {
		return Settings{}, err
	}
	var s Settings
	for key, into := range map[string]*int{"retro-cadence": &s.RetroCadence, "overhaul-cadence": &s.OverhaulCadence, "max-filed": &s.MaxFiled} {
		if err := read(ix, Instance, key, into); err != nil {
			return Settings{}, err
		}
	}
	if err := read(ix, Instance, "manifest-target", &s.ManifestTarget); err != nil {
		return Settings{}, err
	}
	if err := read(ix, Instance, "paused", &s.Paused); err != nil {
		return Settings{}, err
	}
	// A wiring older than issues/stuck, such as main's while it moves, gives
	// the lease its built-in value.
	s.Lease = stuck.Lease
	if stuckAt != "" {
		if err := read(ix, stuckAt, "lease", &s.Lease); err != nil {
			return Settings{}, err
		}
	}
	return s, nil
}

// read reads config key of instance into into.
func read[T any](ix *index.Index, instance, key string, into *T) error {
	name := instance + "/" + index.ConfigPrefix + key
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
