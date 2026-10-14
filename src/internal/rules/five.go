package rules

import (
	"fmt"
	"path"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

// FiveConfig holds the rule of five's limit, the surfaces it reads and its
// allowlist: the one place each lives.
const FiveConfig = "src/internal/rules/five.yaml"

func init() {
	register(Rule{
		Name: "rule-of-five",
		Doc: "each surface " + FiveConfig + " names holds at most its limit of visible files and of visible folders, " +
			"dot entries aside, except as its allowlist says; an allowlist entry only shrinks",
		Applies: func(p string) bool { return p == FiveConfig },
		Check:   ruleOfFive,
	})
}

// five is FiveConfig as it reads: the allowlist by surface, then by what it
// counts ("files" or "folders"), each a node so a finding names its line.
type five struct {
	Limit     int                             `yaml:"limit"`
	Surfaces  []string                        `yaml:"surfaces"`
	Allowlist map[string]map[string]yaml.Node `yaml:"allowlist"`
}

func ruleOfFive(repo *Repo, p string, text []byte) []Finding {
	var found []Finding
	refuse := func(line int, format string, args ...any) {
		found = append(found, Finding{Path: p, Line: line, Rule: "rule-of-five", Message: fmt.Sprintf(format, args...)})
	}
	var c five
	if err := yaml.Unmarshal(text, &c); err != nil {
		refuse(1, "%v", err)
		return found
	}
	if c.Limit < 1 || len(c.Surfaces) == 0 {
		refuse(1, "the configuration names no limit or no surfaces")
		return found
	}
	held := map[string]map[string]int{}
	seen := map[string]bool{}
	for _, s := range c.Surfaces {
		s = path.Clean(s)
		held[s] = map[string]int{"files": 0, "folders": 0}
		for _, f := range repo.Paths {
			rel, ok := f, s == "."
			if !ok {
				rel, ok = strings.CutPrefix(f, s+"/")
			}
			top, _, nested := strings.Cut(rel, "/")
			switch {
			case !ok || strings.HasPrefix(top, "."):
			case !nested:
				held[s]["files"]++
			case !seen[s+"/"+top]:
				seen[s+"/"+top] = true
				held[s]["folders"]++
			}
		}
	}
	for _, surface := range sortedSurfaces(held) {
		for _, kind := range []string{"files", "folders"} {
			n := held[surface][kind]
			entry, listed := c.Allowlist[surface][kind]
			allowed := 0
			if listed {
				if err := entry.Decode(&allowed); err != nil {
					refuse(entry.Line, "allowlist %s %s: %v", surface, kind, err)
					continue
				}
			}
			switch {
			case n > c.Limit && !listed:
				refuse(1, "%s holds %d visible %s, more than %d: move some into a folder (spec/principles.md, principle 21)", show(surface), n, kind, c.Limit)
			case n > c.Limit && n > allowed:
				refuse(entry.Line, "%s holds %d visible %s, more than the %d the allowlist allows: the list only shrinks", show(surface), n, kind, allowed)
			case listed && n <= c.Limit:
				refuse(entry.Line, "%s holds %d visible %s, within the limit: remove its allowlist entry", show(surface), n, kind)
			case listed && n < allowed:
				refuse(entry.Line, "%s holds %d visible %s: lower its allowlist entry from %d to %d", show(surface), n, kind, allowed, n)
			}
		}
	}
	for surface, kinds := range c.Allowlist {
		for kind, entry := range kinds {
			if _, ok := held[path.Clean(surface)]; !ok || (kind != "files" && kind != "folders") {
				refuse(entry.Line, "the allowlist entry %s %s names no surface's files or folders: remove it", surface, kind)
			}
		}
	}
	return found
}

func sortedSurfaces(held map[string]map[string]int) []string {
	out := make([]string, 0, len(held))
	for s := range held {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

// show names a surface as a person reads it: the root as "the root".
func show(surface string) string {
	if surface == "." {
		return "the root"
	}
	return surface + "/"
}
