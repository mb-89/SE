package rules_test

import (
	"sort"
	"strings"
	"testing"
)

func TestAMarkerInCodeNamesItsIssue(t *testing.T) {
	t.Parallel()
	m := "TO" + "DO"
	found := check(t, "todo-issue", map[string]string{
		"a.go":       "package a\n// " + m + "(#12) numbered\n// " + m + " bare\n",
		"b.ts":       "// " + m + ": later\nconst x = 1 // " + m + " see #7\n",
		"c.sh":       "echo " + m + "S are fine\n# " + m + "\n",
		"d.md":       m + " in prose is not code\n",
		"e.yml":      "# " + m + " #\n",
		"f.tsx":      "// " + m + "(#3)\n",
		"g/h.go":     "package h // " + strings.ToLower(m) + " lower case is a word\n",
		"testdata.x": m + "\n",
	})
	want := "a.go:3: todo-issue|b.ts:1: todo-issue|c.sh:2: todo-issue|e.yml:1: todo-issue"
	var got []string
	for _, f := range found {
		got = append(got, f[:strings.Index(f, "todo-issue")+len("todo-issue")])
	}
	sort.Strings(got)
	if strings.Join(got, "|") != want {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
}
