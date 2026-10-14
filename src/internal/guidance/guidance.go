// Package guidance is what an agent gets before it starts: the skills its
// issue names, which the take hands over in full, and the design principles,
// which the session start hands over. Nothing here watches the agent while it
// works; what must hold is checked at the push, by the battery and the landing.
package guidance

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/modules/io/disk"
)

const (
	// Mark ends the line of an issue's body that names the skills its work needs.
	Mark = "<!-- se:skills -->"
	// Dir holds the skills, one folder each, under a checkout.
	Dir = "src/plugin/skills"
	// Principles is the file the session start hands over.
	Principles = "spec/principles.md"
	// Event is the session log's row for a hand-over: the skills, by name and hash.
	Event = "se.guidance"
	// Instance is the wiring's instance of Module, whose config the take and the session start read.
	Instance = "guidance"
)

var skillName = regexp.MustCompile(`^[a-z0-9][a-z0-9-]*$`)

// Parse reads a list of skill names, as `work,retro`; each once, in order.
func Parse(list string) ([]string, error) {
	var names []string
	seen := map[string]bool{}
	for _, n := range strings.Split(list, ",") {
		n = strings.TrimSpace(n)
		if !skillName.MatchString(n) {
			return nil, fmt.Errorf("--skills takes skill names, like work,retro, not %q", list)
		}
		if !seen[n] {
			seen[n] = true
			names = append(names, n)
		}
	}
	return names, nil
}

// Line is the marked line of a body that names the skills.
func Line(names []string) string {
	return "Skills: " + strings.Join(names, ", ") + " " + Mark
}

// With answers body with the line naming the skills at its end; with none, body as it is.
func With(body string, names []string) string {
	if len(names) == 0 {
		return body
	}
	return strings.TrimRight(body, "\n") + "\n\n" + Line(names)
}

// Named answers the skills a body's marked line names; the last such line holds.
func Named(body string) []string {
	var names []string
	for _, line := range strings.Split(body, "\n") {
		rest, ok := strings.CutSuffix(strings.TrimSpace(line), Mark)
		if !ok {
			continue
		}
		rest = strings.TrimPrefix(strings.TrimSpace(rest), "Skills:")
		if parsed, err := Parse(rest); err == nil {
			names = parsed
		}
	}
	return names
}

// Skill is one skill as it was handed over.
type Skill struct {
	Name string `json:"name"`
	// Path is the skill's file, relative to the checkout.
	Path string `json:"path"`
	// Hash is the SHA-256 of the text handed over, in hex.
	Hash string `json:"hash"`
	// Text is the skill's whole file.
	Text string `json:"-"`
}

// PathOf is the file of the skill name, relative to a checkout.
func PathOf(name string) string { return filepath.ToSlash(filepath.Join(Dir, name, "SKILL.md")) }

// Read answers each named skill from the checkout at workspace; a name with no skill there fails.
func Read(d disk.Disk, workspace string, names []string) ([]Skill, error) {
	skills := make([]Skill, 0, len(names))
	for _, n := range names {
		path := PathOf(n)
		data, err := d.ReadFile(filepath.Join(workspace, path))
		if err != nil {
			return nil, fmt.Errorf("no skill %s: %s cannot be read: %v", n, path, err)
		}
		sum := sha256.Sum256(data)
		skills = append(skills, Skill{Name: n, Path: path, Hash: hex.EncodeToString(sum[:]), Text: string(data)})
	}
	return skills, nil
}

// Body is a skill's or an agent's file without its front matter.
func Body(text []byte) string {
	t := string(text)
	if rest, ok := strings.CutPrefix(t, "---\n"); ok {
		if _, body, ok := strings.Cut(rest, "\n---\n"); ok {
			return body
		}
	}
	return t
}

// Text is the skills as an answer carries them: in full where inline holds,
// else each by name and file only.
func Text(skills []Skill, inline bool) string {
	if len(skills) == 0 {
		return ""
	}
	var b strings.Builder
	if !inline {
		b.WriteString("The issue names these skills; read each before you start:")
		for _, s := range skills {
			fmt.Fprintf(&b, "\n- %s: %s", s.Name, s.Path)
		}
		return b.String()
	}
	b.WriteString("The issue names these skills; each follows in full. Follow them.")
	for _, s := range skills {
		fmt.Fprintf(&b, "\n\n<skill name=%q path=%q>\n%s\n</skill>", s.Name, s.Path, strings.TrimRight(s.Text, "\n"))
	}
	return b.String()
}

// Module declares the switches of the hand-over, read like any config value.
var Module = index.Declare("guidance", "What an agent gets before it starts: the skills its issue names, and the design principles.",
	index.Config("inline", true, "Whether a take prints the full text of each skill its issue names; off, it names them only."),
	index.Config("principles", true, "Whether a session starts with spec/principles.md in its context."),
)

func init() { index.Register(Module) }

// Settings are Module's config values as the wiring the se binary carries gives them.
type Settings struct {
	Inline, Principles bool
}

// Configured answers the settings of Instance from the wiring se carries.
func Configured() (Settings, error) {
	w, err := index.Wired()
	if err != nil {
		return Settings{}, err
	}
	return From(w)
}

// From answers the settings of Instance as the wiring w gives them. It starts
// an index of w's guidance instances alone, so it needs no other module.
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
	for key, into := range map[string]*bool{"inline": &s.Inline, "principles": &s.Principles} {
		v, err := ix.Read(Instance + "/" + index.ConfigPrefix + key)
		if err != nil {
			return Settings{}, err
		}
		b, ok := v.V.(bool)
		if !ok {
			return Settings{}, fmt.Errorf("%s/%s%s is no bool: %v", Instance, index.ConfigPrefix, key, v.V)
		}
		*into = b
	}
	return s, nil
}
