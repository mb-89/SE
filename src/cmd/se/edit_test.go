// Internal test package: it drives the registered commands through se and hubAt.
package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestIssueEditRewritesThroughSeKeepingTheMark(t *testing.T) {
	t.Parallel()
	gh := hubAt(t, map[string]string{
		"repos/o/r/issues?labels=se&state=open&per_page=100": `[{"number":3,"title":"three","state":"open"}]`,
		"repos/o/r/issues/3": `{"id":103,"number":3,"state":"open","title":"three","html_url":"u3","body":"do it\n\nSkills: work <!-- se:skills -->\n\n<!-- se:new -->","labels":[{"name":"se"}]}`,
	})
	for args, want := range map[string]string{
		"":                         "takes one issue number",
		"3 4":                      "takes one issue number",
		"3 --body b --body-file f": "one of --body and --body-file",
		"9":                        "#9 does not exist in o/r",
		"3 --title=":               "needs a --title",
	} {
		code, _, errs := se(t, append([]string{"issue", "edit", "--repo", "o/r"}, strings.Fields(args)...)...)
		if code != 1 || !strings.Contains(errs, want) {
			t.Errorf("%q: exit %d, %q, want %q", args, code, errs, want)
		}
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused issue edit wrote %q", w)
	}
	dir := filepath.FromSlash("/ws")
	put(t, onFake(t), filepath.Join(dir, "body.md"), "do it better\n")
	code, out, errs := se(t, "issue", "edit", "#3", "--title", "three, sharper", "--body-file", "body.md", "--workspace", dir, "--repo", "o/r")
	if code != 0 || out != "Edited #3 three, sharper, its mark kept.\nu3\nKept from the old body: Skills: work <!-- se:skills -->\n" {
		t.Fatalf("exit %d, %q, %q", code, out, errs)
	}
	if got := issueOf(t, gh, 3); !strings.Contains(got, `"body":"do it better\n\nSkills: work <!-- se:skills -->\n\n<!-- se:new -->"`) {
		t.Fatalf("%s", got)
	}
}
