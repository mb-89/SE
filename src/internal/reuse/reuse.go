// Package reuse is what SE runs that others built: the outside plugins and
// skills, each pinned to a commit, and which of them each tier of agent runs,
// staggered by cost. The worker runs a light pass, the reviewer heavier ones
// once per gate, the overhaul the heaviest over everything, and whoever
// writes or changes an SE agent or skill runs the author's. Which tier runs
// what is one config value per tier, in the wiring; the take and the brief
// hand each tier its list, resolved against the plugins this box loaded.
package reuse

import (
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/internal/io/disk"
)

const (
	// Instance is the wiring's instance of Module, whose config the take, the brief and the fetch read.
	Instance = "reuse"
	// Adopted is the plugin se fetch makes to serve the lone skills, so a
	// skill source named clean-code runs as adopted:clean-code.
	Adopted = "adopted"
	// DirsVar names the plugin folders a session loads (spec/cloud.md):
	// several, separated as the system separates paths.
	DirsVar = "CLAUDE_CODE_PLUGIN_DIRS"
)

// The tiers, cheapest first.
const (
	Worker   = "worker"
	Reviewer = "reviewer"
	Overhaul = "overhaul"
	Author   = "author"
)

// Tiers are every tier, in the order the config declares them.
var Tiers = []string{Worker, Reviewer, Overhaul, Author}

// Source is one outside plugin or skill SE runs, pinned to a commit.
type Source struct {
	// Name is the plugin's name, or, for a lone skill, the skill's.
	Name string `yaml:"name" json:"name"`
	// Repo is the GitHub repository it comes from, as OWNER/NAME.
	Repo string `yaml:"repo" json:"repo"`
	// Path is its folder inside Repo; "." is the repository's root.
	Path string `yaml:"path" json:"path"`
	// Commit is the full commit it is pinned to.
	Commit string `yaml:"commit" json:"commit"`
	// Licence is its SPDX licence, as read at Commit.
	Licence string `yaml:"licence" json:"licence"`
	// Skill marks a lone skill, which the Adopted plugin serves.
	Skill bool `yaml:"skill,omitempty" json:"skill,omitempty"`
}

// Plugin is the plugin a session loads the source as.
func (s Source) Plugin() string {
	if s.Skill {
		return Adopted
	}
	return s.Name
}

// Config is Module's config: the sources, each tier's list and the places
// the overhaul looks for more.
type Config struct {
	Sources []Source
	// Tier holds each tier's list: a built-in skill by its name, as
	// simplify, and a plugin's skill or agent as plugin:name.
	Tier map[string][]string
	// Places are where the overhaul's outside look searches for what SE
	// could adopt instead of keeping its own.
	Places []string
}

// Module declares the sources, the tiers and the places, read like any config value.
var Module = index.Declare("reuse", "What SE runs that others built: the outside plugins and skills, pinned, and which of them each tier of agent runs.",
	index.Config("sources", []Source(nil), "Every outside plugin and lone skill SE runs, each pinned to a commit with its licence; se fleet plugins fetches them."),
	index.Config(Worker, []string(nil), "What a worker runs on its own diff before it commits: light, inside the battery's time budget."),
	index.Config(Reviewer, []string(nil), "What a gate's reviewer runs on its delta, once per gate; its report names each (ran)."),
	index.Config(Overhaul, []string(nil), "What an overhaul runs over the whole code, taking as long as it needs."),
	index.Config(Author, []string(nil), "What whoever writes or changes an SE agent or skill runs on it."),
	index.Config("places", []string(nil), "Where the overhaul's outside look searches for what SE could adopt instead of keeping its own."),
)

func init() { index.Register(Module) }

// Configured answers the config of Instance from the wiring se carries.
func Configured() (Config, error) {
	w, err := index.Wired()
	if err != nil {
		return Config{}, err
	}
	return From(w)
}

// From answers the config of Instance as the wiring w gives it, checked. It
// starts an index of w's reuse instances alone, so it needs no other module.
func From(w index.Wiring) (Config, error) {
	own := index.Wiring{}
	for _, in := range w.Instances {
		if in.Module == Module.Name() {
			own.Instances = append(own.Instances, in)
		}
	}
	ix, err := index.Start(own, Module)
	if err != nil {
		return Config{}, err
	}
	read := func(key string) (any, error) {
		v, err := ix.Read(Instance + "/" + index.ConfigPrefix + key)
		return v.V, err
	}
	c := Config{Tier: map[string][]string{}}
	v, err := read("sources")
	if err != nil {
		return Config{}, err
	}
	c.Sources, _ = v.([]Source)
	for _, key := range append([]string{"places"}, Tiers...) {
		v, err := read(key)
		if err != nil {
			return Config{}, err
		}
		list, _ := v.([]string)
		if key == "places" {
			c.Places = list
		} else {
			c.Tier[key] = list
		}
	}
	return c, c.Check()
}

var (
	repoName = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	fullSHA  = regexp.MustCompile(`^[0-9a-f]{40}$`)
	itemName = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)
)

// Check refuses a config whose source is not pinned, whose licence is not
// named, or whose tier names a plugin no source provides.
func (c Config) Check() error {
	plugins := map[string]bool{}
	for _, s := range c.Sources {
		switch {
		case !itemName.MatchString(s.Name):
			return fmt.Errorf("reuse: source %q needs a name of lowercase letters, digits and dashes", s.Name)
		case s.Name == Adopted && !s.Skill:
			return fmt.Errorf("reuse: no plugin source may be named %s, the plugin that serves the lone skills", Adopted)
		case plugins[s.Name] || (s.Skill && plugins["skill:"+s.Name]):
			return fmt.Errorf("reuse: source %s is named twice", s.Name)
		case !repoName.MatchString(s.Repo):
			return fmt.Errorf("reuse: source %s names no repository OWNER/NAME: %q", s.Name, s.Repo)
		case !fullSHA.MatchString(s.Commit):
			return fmt.Errorf("reuse: source %s is pinned to no full commit: %q", s.Name, s.Commit)
		case strings.TrimSpace(s.Licence) == "":
			return fmt.Errorf("reuse: source %s names no licence: read it, and adopt nothing without one", s.Name)
		case s.Path == "" || filepath.IsAbs(s.Path) || strings.Contains(s.Path, ".."):
			return fmt.Errorf("reuse: source %s needs a path inside its repository, \".\" for the root: %q", s.Name, s.Path)
		}
		if s.Skill {
			plugins["skill:"+s.Name] = true
			plugins[Adopted] = true
		} else {
			plugins[s.Name] = true
		}
	}
	for _, tier := range Tiers {
		for _, entry := range c.Tier[tier] {
			plugin, item, scoped := strings.Cut(entry, ":")
			if !scoped {
				item = plugin
			}
			switch {
			case !itemName.MatchString(item) || (scoped && !itemName.MatchString(plugin)):
				return fmt.Errorf("reuse: %s names %q, which is neither a built-in skill nor plugin:name", tier, entry)
			case scoped && !plugins[plugin]:
				return fmt.Errorf("reuse: %s names %s, but no source provides the plugin %s", tier, entry, plugin)
			case scoped && plugin == Adopted && !plugins["skill:"+item]:
				return fmt.Errorf("reuse: %s names %s, but no lone skill source is named %s", tier, entry, item)
			}
		}
	}
	return nil
}

// Entry is one name of a tier, as this box can run it.
type Entry struct {
	// Name is the tier's name for it: simplify, or plugin:name.
	Name string
	// Kind is "built-in", "skill" or "agent"; "" where this box lacks it.
	Kind string
	// File is an agent's file, which a sub-agent that cannot start agents follows.
	File string
	// Source is where a plugin's entry comes from, as repo@commit.
	Source string
}

// Resolve answers each name of tier as this box can run it: dirs are the
// plugin folders the session loaded (DirsVar), each a plugin or a folder of
// plugins, as Claude Code reads them.
func (c Config) Resolve(d disk.Disk, tier string, dirs []string) []Entry {
	out := []Entry{}
	for _, name := range c.Tier[tier] {
		plugin, item, scoped := strings.Cut(name, ":")
		if !scoped {
			out = append(out, Entry{Name: name, Kind: "built-in"})
			continue
		}
		e := Entry{Name: name}
		for _, s := range c.Sources {
			if s.Plugin() == plugin && (!s.Skill || s.Name == item) {
				e.Source = fmt.Sprintf("%s@%s", s.Repo, s.Commit[:12])
				break
			}
		}
		for _, root := range pluginRoots(d, plugin, dirs) {
			if file := filepath.Join(root, "agents", item+".md"); exists(d, file) {
				e.Kind, e.File = "agent", file
			} else if exists(d, filepath.Join(root, "skills", item, "SKILL.md")) || exists(d, filepath.Join(root, "commands", item+".md")) {
				e.Kind = "skill"
			}
			if e.Kind != "" {
				break
			}
		}
		out = append(out, e)
	}
	return out
}

// Dirs splits the value of DirsVar as Claude Code does.
func Dirs(value string) []string {
	var out []string
	for _, d := range filepath.SplitList(value) {
		if d = strings.TrimSpace(d); d != "" {
			out = append(out, d)
		}
	}
	return out
}

// pluginRoots are the folders among dirs that may hold plugin: a folder
// named after it, or its child of that name.
func pluginRoots(d disk.Disk, plugin string, dirs []string) []string {
	var out []string
	for _, dir := range dirs {
		if filepath.Base(dir) == plugin {
			out = append(out, dir)
		}
		if child := filepath.Join(dir, plugin); exists(d, filepath.Join(child, ".claude-plugin", "plugin.json")) {
			out = append(out, child)
		}
	}
	return out
}

func exists(d disk.Disk, path string) bool {
	ok, err := d.Exists(path)
	return err == nil && ok
}

// Text is what an agent of a tier is handed: intro, which says when to run
// them and on what, then each entry and how this box runs it.
func Text(intro string, entries []Entry) string {
	if len(entries) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString(intro)
	for _, e := range entries {
		switch e.Kind {
		case "built-in":
			fmt.Fprintf(&b, "\n- %s: a built-in skill; run it with the Skill tool (/%s).", e.Name, e.Name)
		case "skill":
			fmt.Fprintf(&b, "\n- %s: a skill from %s; run it with the Skill tool.", e.Name, e.Source)
		case "agent":
			fmt.Fprintf(&b, "\n- %s: an agent from %s; start it with the Agent tool, or, where you cannot start one, read %s and do its pass yourself.", e.Name, e.Source, e.File)
		default:
			fmt.Fprintf(&b, "\n- %s: not on this box, since no folder of %s holds its plugin (spec/cloud.md); say that it did not run, and why.", e.Name, DirsVar)
		}
	}
	return b.String()
}
