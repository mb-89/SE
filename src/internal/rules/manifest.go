package rules

import (
	"fmt"
	"path"
	"regexp"
	"strings"
)

// A manifest is a generated map that points at owners and says nothing of its
// own: a section between <!-- se:manifest NAME --> and <!-- /se:manifest -->,
// written by se manifest from the owners.
var (
	manifestOpen  = regexp.MustCompile(`^<!-- se:manifest (\S.*?) -->$`)
	manifestClose = "<!-- /se:manifest -->"
)

func init() {
	register(Rule{
		Name:    "manifest",
		Doc:     "every manifest section is what se manifest --write writes from its owners",
		Applies: func(p string) bool { return path.Ext(p) == ".md" },
		Check: func(repo *Repo, p string, text []byte) []Finding {
			_, found := Manifests(p, text, func(name string) (string, error) {
				if repo.Manifest == nil {
					return "", fmt.Errorf("no manifest is known")
				}
				return repo.Manifest(name, p)
			})
			return found
		},
	})
}

// Manifests answers the file with every manifest section rewritten by gen, and
// what is wrong with them as committed: a section that differs from gen's,
// one gen cannot make, or one left open.
func Manifests(p string, text []byte, gen func(name string) (string, error)) ([]byte, []Finding) {
	var out []string
	var found []Finding
	lines := strings.Split(string(text), "\n")
	for i := 0; i < len(lines); i++ {
		out = append(out, lines[i])
		m := manifestOpen.FindStringSubmatch(lines[i])
		if m == nil {
			continue
		}
		name, open := m[1], i
		end := -1
		for j := i + 1; j < len(lines); j++ {
			if lines[j] == manifestClose {
				end = j
				break
			}
			if manifestOpen.MatchString(lines[j]) {
				break
			}
		}
		if end < 0 {
			found = append(found, Finding{Path: p, Line: open + 1, Rule: "manifest", Message: fmt.Sprintf("manifest %q has no %s", name, manifestClose)})
			continue
		}
		have := strings.Join(lines[open+1:end], "\n")
		want, err := gen(name)
		if err != nil {
			found = append(found, Finding{Path: p, Line: open + 1, Rule: "manifest", Message: fmt.Sprintf("manifest %q: %v", name, err)})
			want = have
		}
		want = strings.TrimRight(want, "\n")
		if err == nil && want != have {
			found = append(found, Finding{Path: p, Line: open + 1, Rule: "manifest", Message: fmt.Sprintf("manifest %q differs from what its owners make; run se manifest --write", name)})
		}
		if want != "" {
			out = append(out, want)
		}
		out = append(out, manifestClose)
		i = end
	}
	return []byte(strings.Join(out, "\n")), found
}
