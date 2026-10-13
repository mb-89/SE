package rules_test

import (
	"errors"
	"sort"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/rules"
)

// registry is a small command registry: issue next and issue land under
// issue, and help.
var registry = map[string][]string{
	"issue next": {"take", "in", "json"},
	"issue land": {"answers"},
	"help":       {},
}

func sorted(found []string) string {
	sort.Strings(found)
	return strings.Join(found, "\n")
}

func TestEverySeCommandProseNamesExists(t *testing.T) {
	found := checkIn(t, &rules.Repo{Commands: registry}, "se-command", map[string]string{
		"README.md": "Run `se issue next --take` or `/se issue land --answers F`.\n" +
			"Not `se issue take`, nor `./src/plugin/bin/se issue next --tak=5`.\n" +
			"`se frob` is gone; `se --session help` and `se <command>` are fine.\n" +
			"`<se> issue next [--in ROOT] [--json]`, `se issue …`, `cd /opt/se && go build`.\n" +
			"```sh\nse issue next --take && se issue nest\n```\n" +
			"`se help issue next` takes words; `se --verbose help` has no such flag.\n",
		"spec/a.yaml": "# the `se issue next --person` list\n",
		"notes.txt":   "`se frob` in a file that is not prose\n",
	})
	want := sorted([]string{
		"README.md:2: se-command: se has no command \"issue take\"",
		"README.md:2: se-command: se issue next takes no flag --tak",
		"README.md:3: se-command: se has no command \"frob\"",
		"README.md:6: se-command: se has no command \"issue nest\"",
		"README.md:8: se-command: se takes no flag --verbose before a command",
		"spec/a.yaml:1: se-command: se issue next takes no flag --person",
	})
	if got := sorted(found); got != want {
		t.Fatalf("found:\n%s\nwant:\n%s", got, want)
	}
}

func TestEveryPathAndLinkProseNamesExists(t *testing.T) {
	found := checkIn(t, &rules.Repo{Ignored: func(p string) bool { return p == "src/bin/se" }}, "repo-path", map[string]string{
		"README.md": "See `src/a/b.go`, `./src/a/`, `src/bin/se` and `src/a/gone.go`.\n" +
			"Not paths: `origin/main`, `src/<name>/x.md`, `/opt/se`, `git diff a..b`, `issue-<n>`.\n" +
			"[a](spec/rules.md#the-rules), [b](spec/gone.md), [c](https://x.y/z), [d](#top), [e](../out.md)\n" +
			"```\ncat src/a/fenced-is-shell.go\n```\n" +
			"`[f](spec/gone2.md)` is code, not a link.\n",
		"spec/rules.md": "[back](../README.md) and [miss](./nope.md)\n",
		"src/a/b.go":    "package a\n",
	})
	want := sorted([]string{
		"README.md:1: repo-path: no such path: src/a/gone.go",
		"README.md:3: repo-path: the link names no such path: spec/gone.md",
		"README.md:3: repo-path: the link leaves the repository: ../out.md",
		"spec/rules.md:1: repo-path: the link names no such path: ./nope.md",
	})
	if got := sorted(found); got != want {
		t.Fatalf("found:\n%s\nwant:\n%s", got, want)
	}
}

func TestAManifestIsWhatItsOwnersMake(t *testing.T) {
	gen := func(name, at string) (string, error) {
		if name != "list" {
			return "", errors.New("no such manifest")
		}
		return "- one\n- two (in " + at + ")\n", nil
	}
	found := checkIn(t, &rules.Repo{Manifest: gen}, "manifest", map[string]string{
		"a.md": "# A\n<!-- se:manifest list -->\n- one\n- two (in a.md)\n<!-- /se:manifest -->\n",
		"b.md": "# B\n\n<!-- se:manifest list -->\n- one\n- two, edited by hand\n<!-- /se:manifest -->\n",
		"c.md": "<!-- se:manifest other -->\n<!-- /se:manifest -->\n<!-- se:manifest list -->\n- one\n",
	})
	want := sorted([]string{
		"b.md:3: manifest: manifest \"list\" differs from what its owners make; run se manifest --write",
		"c.md:1: manifest: manifest \"other\": no such manifest",
		"c.md:3: manifest: manifest \"list\" has no <!-- /se:manifest -->",
	})
	if got := sorted(found); got != want {
		t.Fatalf("found:\n%s\nwant:\n%s", got, want)
	}
}

func TestManifestsRewritesEverySection(t *testing.T) {
	text := "# A\n<!-- se:manifest x -->\nstale\n<!-- /se:manifest -->\nkept\n<!-- se:manifest x -->\n<!-- /se:manifest -->\n"
	out, found := rules.Manifests("a.md", []byte(text), func(string) (string, error) { return "made\n", nil })
	want := "# A\n<!-- se:manifest x -->\nmade\n<!-- /se:manifest -->\nkept\n<!-- se:manifest x -->\nmade\n<!-- /se:manifest -->\n"
	if string(out) != want || len(found) != 2 {
		t.Fatalf("out:\n%s\nfound: %v", out, found)
	}
}

func TestEveryMarkdownFileNamesItsReader(t *testing.T) {
	found := check(t, "reader", map[string]string{
		"a.md":       "# A\n\nReader: a person meeting SE.\n\nText.\n",
		"b.md":       "---\nname: b\n---\n\n# B\n\nReaders: the agent running it.\n",
		"c.md":       "Reader: anyone.\n",
		"d.md":       "# D\n\nText first.\n\nReader: too late.\n",
		"e.md":       "",
		"f/SKILL.md": "---\nname: f\n---\n# F\nSteps.\n",
		"g.txt":      "no reader needed\n",
	})
	want := sorted([]string{
		"d.md:3: reader: the file names no reader; under its title, write one line: Reader: <who reads it, and what for>",
		"e.md:1: reader: the file names no reader; under its title, write one line: Reader: <who reads it, and what for>",
		"f/SKILL.md:5: reader: the file names no reader; under its title, write one line: Reader: <who reads it, and what for>",
	})
	if got := sorted(found); got != want {
		t.Fatalf("found:\n%s\nwant:\n%s", got, want)
	}
}
