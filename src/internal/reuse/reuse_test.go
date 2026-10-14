package reuse_test

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/reuse"
)

const pin = "8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3"

// wired is a wiring holding one reuse instance with config.
func wired(t *testing.T, config string) (reuse.Config, error) {
	t.Helper()
	w, err := index.ParseWiring([]byte("instances:\n  reuse:\n    module: reuse\n    config:\n" + config))
	if err != nil {
		t.Fatal(err)
	}
	return reuse.From(w)
}

func TestTheConfigSeCarriesIsPinnedAndEveryTierNamesWhatASourceProvides(t *testing.T) {
	t.Parallel()
	c, err := reuse.Configured()
	if err != nil {
		t.Fatal(err)
	}
	for _, tier := range reuse.Tiers {
		if len(c.Tier[tier]) == 0 {
			t.Errorf("the %s runs nothing", tier)
		}
	}
	if len(c.Places) == 0 {
		t.Error("the overhaul has no places to look")
	}
}

func TestAConfigThatIsNotPinnedOrNamesWhatNoSourceProvidesIsRefused(t *testing.T) {
	t.Parallel()
	src := func(name, commit, licence, path string) string {
		return "      sources: [{name: " + name + ", repo: o/r, path: '" + path + "', commit: '" + commit + "', licence: '" + licence + "'}]\n"
	}
	for config, want := range map[string]string{
		src("p", "main", "MIT", "."):                                                           "pinned to no full commit",
		src("p", pin, "", "."):                                                                 "names no licence",
		src("p", pin, "MIT", "../x"):                                                           "needs a path inside its repository",
		src("adopted", pin, "MIT", "."):                                                        "no plugin source may be named adopted",
		src("p", pin, "MIT", ".") + "      worker: [q:x]\n":                                    "no source provides the plugin q",
		src("p", pin, "MIT", ".") + "      reviewer: [adopted:x]\n":                            "no source provides the plugin adopted",
		src("p", pin, "MIT", ".") + "      overhaul: ['Not A Name']\n":                         "neither a built-in skill nor plugin:name",
		"      sources: [{name: p, repo: nope, path: ., commit: " + pin + ", licence: MIT}]\n": "names no repository",
	} {
		if _, err := wired(t, config); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: %v, want %q", config, err, want)
		}
	}
	c, err := wired(t, "      sources: [{name: s, repo: o/r, path: ., commit: "+pin+", licence: MIT, skill: true}]\n      author: [adopted:s, simplify]\n")
	if err != nil || len(c.Tier[reuse.Author]) != 2 || c.Sources[0].Plugin() != reuse.Adopted {
		t.Fatalf("%+v %v", c, err)
	}
}
