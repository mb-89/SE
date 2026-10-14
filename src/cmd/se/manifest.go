package main

import (
	"bytes"
	"fmt"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/rules"
)

// A manifest is a map: it points at owners and says nothing of its own, so it
// is made from them, never written by hand. Each one here reads its owner: the
// registry of kinds, the skills folder, spec/, the command registry, or the
// retro's rule checks.
var manifests = map[string]func(m manifestCall) (string, error){
	"agents": agentsManifest,
	"checks": checksManifest,
	"skills": skillsManifest,
	"spec":   specManifest,
	"usage":  usageManifest,
}

// manifestCall is what a manifest is made for: the checkout, its files, the
// words after the manifest's name, and the file the section stands in.
type manifestCall struct {
	disk  disk.Disk
	root  string
	paths []string
	args  []string
	at    string
}

// link is the target of a link from the file the section stands in to p.
func (m manifestCall) link(p string) string {
	rel, err := filepath.Rel(filepath.FromSlash(path.Dir(m.at)), filepath.FromSlash(p))
	if err != nil {
		return p
	}
	return filepath.ToSlash(rel)
}

func init() {
	register(Command{
		Name:    "manifest",
		Class:   batch,
		Usage:   "manifest [--write] [<name>]",
		Group:   "Checks",
		Summary: "print a manifest, or rewrite every manifest section",
		Details: []string{
			"A manifest section stands between <!-- se:manifest <name> --> and <!-- /se:manifest --> in a Markdown file, and is made from its owners: agents (the registry of kinds and the plugin's agents), checks (the retro's rule checks), skills (the skills folder), spec (spec/), usage <word>... (the usage lines of the commands under each word).",
			"With a name, manifest prints that manifest; with --write, it rewrites every section of every Markdown file git tracks and names the files it changed, and refuses while git's index holds unmerged paths.",
			"The rule manifest fails where a committed section differs.",
		},
		Run: func(c *Call) (Reply, error) {
			fs := c.Flags("manifest")
			write := fs.Bool("write", false, "rewrite every manifest section in the checkout")
			if err := fs.Parse(c.Args); err != nil {
				return Reply{}, err
			}
			name := strings.Join(fs.Args(), " ")
			root, err := filepath.Abs(c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			c.Workspace = root
			repo, err := repoOf(c.Disk, c.Proc, c.Workspace)
			if err != nil {
				return Reply{}, err
			}
			if !*write {
				if name == "" {
					return Reply{}, fmt.Errorf("manifest takes a name (%s), or --write", strings.Join(manifestNames(), ", "))
				}
				text, err := manifest(c.Disk, c.Workspace, repo.Paths, name, "README.md")
				return Reply{Text: text}, err
			}
			if unmerged, err := unmergedPaths(c.Proc, c.Workspace); err != nil {
				return Reply{}, err
			} else if len(unmerged) > 0 {
				return Reply{}, fmt.Errorf("manifest --write refuses while git's index holds unmerged paths (%s): resolve the merge first", strings.Join(unmerged, ", "))
			}
			var changed []string
			for _, p := range repo.Paths {
				if path.Ext(p) != ".md" {
					continue
				}
				full := filepath.Join(c.Workspace, filepath.FromSlash(p))
				text, err := c.Disk.ReadFile(full)
				if err != nil {
					continue
				}
				out, found := rules.Manifests(p, text, func(n string) (string, error) { return manifest(c.Disk, c.Workspace, repo.Paths, n, p) })
				for _, f := range found {
					if !strings.Contains(f.Message, "differs") {
						return Reply{}, fmt.Errorf("%s", f)
					}
				}
				if !bytes.Equal(out, text) {
					if err := c.Disk.WriteFile(full, out); err != nil {
						return Reply{}, err
					}
					changed = append(changed, p)
				}
			}
			if len(changed) == 0 {
				return Reply{Text: "every manifest is current"}, nil
			}
			return Reply{Text: "rewrote " + strings.Join(changed, ", ")}, nil
		},
	})
}

func manifestNames() []string {
	var names []string
	for n := range manifests {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}

// manifest makes the manifest named, its first word the manifest and the rest
// its words, for a section in the file at.
func manifest(d disk.Disk, root string, paths []string, name, at string) (string, error) {
	words := strings.Fields(name)
	if len(words) == 0 {
		return "", fmt.Errorf("a manifest needs a name")
	}
	made, ok := manifests[words[0]]
	if !ok {
		return "", fmt.Errorf("se makes no manifest %q; it makes %s", words[0], strings.Join(manifestNames(), ", "))
	}
	return made(manifestCall{disk: d, root: root, paths: paths, args: words[1:], at: at})
}

// agentsManifest lists the plugin's agents, each by its type in a session,
// linked to its file, with the kind of issue it works, from the registry of kinds.
func agentsManifest(m manifestCall) (string, error) {
	var lines []string
	for _, k := range issues.IssueKinds {
		if ok, err := m.disk.Exists(filepath.Join(m.root, filepath.FromSlash(k.File()))); err != nil || !ok {
			return "", fmt.Errorf("the %s kind's agent has no file %s", k.Name, k.File())
		}
		lines = append(lines, fmt.Sprintf("- [`%s`](%s), for the kind %s: %s.", k.Type(), m.link(k.File()), k.Name, k.What))
	}
	return strings.Join(lines, "\n"), nil
}

// skillsManifest lists the plugin's skills, each by its name in a session,
// linked, with its own description.
func skillsManifest(m manifestCall) (string, error) {
	var lines []string
	for _, p := range m.paths {
		dir, file := path.Split(p)
		if file != "SKILL.md" || path.Dir(path.Clean(dir)) != "src/plugin/skills" {
			continue
		}
		text, err := m.disk.ReadFile(filepath.Join(m.root, filepath.FromSlash(p)))
		if err != nil {
			return "", err
		}
		name, description := frontmatter(text, "name"), frontmatter(text, "description")
		if name == "" || description == "" {
			return "", fmt.Errorf("%s has no name or no description", p)
		}
		lines = append(lines, fmt.Sprintf("- [`se:%s`](%s): %s", name, m.link(p), description))
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n"), nil
}

// specManifest lists the files in spec/, each linked, with its title where it has one.
func specManifest(m manifestCall) (string, error) {
	var lines []string
	for _, p := range m.paths {
		if path.Dir(p) != "spec" {
			continue
		}
		line := fmt.Sprintf("- [%s](%s)", p, m.link(p))
		if path.Ext(p) == ".md" {
			text, err := m.disk.ReadFile(filepath.Join(m.root, filepath.FromSlash(p)))
			if err != nil {
				return "", err
			}
			for _, l := range strings.Split(string(text), "\n") {
				if title, ok := strings.CutPrefix(l, "# "); ok {
					line += ": " + title
					break
				}
			}
		}
		lines = append(lines, line)
	}
	sort.Strings(lines)
	return strings.Join(lines, "\n"), nil
}

// checksManifest lists the retro's rule checks, each with the PR it is
// checked from and whether it holds closing or creation against it.
func checksManifest(manifestCall) (string, error) {
	var lines []string
	for _, k := range issues.RuleChecks() {
		from := "from the first commit"
		if k.Since > 0 {
			when := "closed"
			if k.Bound == issues.Creation {
				when = "was created"
			}
			from = fmt.Sprintf("on what %s after PR #%d brought it", when, k.Since)
		}
		lines = append(lines, fmt.Sprintf("- `%s`: %s; checked %s.", k.Kind, k.Rule, from))
	}
	return strings.Join(lines, "\n"), nil
}

// usageManifest lists the usage lines of the commands under each word, as the
// registry has them.
func usageManifest(m manifestCall) (string, error) {
	if len(m.args) == 0 {
		return "", fmt.Errorf("usage takes the words whose commands it lists: usage issue review")
	}
	var lines []string
	for _, w := range m.args {
		n := len(lines)
		for _, c := range offered(false) {
			if c.Name == w || strings.HasPrefix(c.Name, w+" ") {
				lines = append(lines, "se "+c.Usage)
			}
		}
		if len(lines) == n {
			return "", fmt.Errorf("se has no command under %q", w)
		}
	}
	return "```\n" + strings.Join(lines, "\n") + "\n```", nil
}

// frontmatter answers a key's value in a file's front matter.
func frontmatter(text []byte, key string) string {
	lines := strings.Split(string(text), "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[0]) != "---" {
		return ""
	}
	for _, l := range lines[1:] {
		if strings.TrimSpace(l) == "---" {
			break
		}
		if v, ok := strings.CutPrefix(l, key+":"); ok {
			return strings.TrimSpace(v)
		}
	}
	return ""
}
