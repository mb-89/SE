package rules_test

import (
	"maps"
	"strings"
	"testing"
)

// The doors a case stands on, each its owns.yaml as a fixture: small, so a
// case reads what it finds off them.
const (
	clockDoor  = "guards: \"the clock: the time now\"\ngo: [time.Now, time.Sleep, time.After]\n"
	diskDoor   = "guards: \"the disk: files\"\ngo: [os.ReadFile, path/filepath.Walk, path/filepath.WalkDir, path/filepath.Glob]\ncommands: []\n"
	procDoor   = "guards: \"processes: programs\"\ngo: [os/exec]\n"
	httpDoor   = "guards: \"the network: HTTP\"\ngo: [net/http]\n"
	githubDoor = "guards: \"GitHub: issues, pull requests\"\ngo: [github.com/google/go-github]\ncommands: [gh, api.github.com, mcp__github__*]\n"
)

// withDoors answers files with every door's declaration beside them.
func withDoors(files map[string]string) map[string]string {
	out := map[string]string{
		"src/internal/io/clock/owns.yaml":  clockDoor,
		"src/internal/io/disk/owns.yaml":   diskDoor,
		"src/internal/io/proc/owns.yaml":   procDoor,
		"src/internal/io/http/owns.yaml":   httpDoor,
		"src/internal/io/github/owns.yaml": githubDoor,
	}
	maps.Copy(out, files)
	return out
}

func TestOnlyIOModulesReachTheOutside(t *testing.T) {
	t.Parallel()
	found := check(t, "io-module", withDoors(map[string]string{
		"src/a/proc.go":                  "package a\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/net.go":                   "package a\n\nimport _ \"net/http\"\n",
		"src/a/sub.go":                   "package a\n\nimport _ \"github.com/google/go-github/v60/github\"\n",
		"src/a/clock.go":                 "package a\n\nimport tm \"time\"\n\nvar now = tm.Now\n\nfunc f() { tm.Sleep(tm.Second); <-tm.After(0) }\n",
		"src/a/disk.go":                  "package a\n\nimport \"os\"\n\nfunc f() { _, _ = os.ReadFile(\"x\"); _ = os.Getenv(\"HOME\") }\n",
		"src/a/pure.go":                  "package a\n\nimport (\n\t\"os\"\n\t\"time\"\n)\n\nvar d = time.Second\nvar e = os.Getenv\n",
		"src/a/a_test.go":                "package a_test\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/kept.go":                  "package a\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/hub.go":                   "package a\n\nimport run \"os/exec\"\n\nvar _ = run.Command(\"gh\", \"api\")\nvar _ = run.Command(\"git\")\nvar _ = run.Command(\"ghost\")\n",
		"src/internal/io/github/gh.go":   "package github\n\nimport \"os/exec\"\n\nvar _ = exec.Command(\"gh\")\n",
		"src/internal/io/clock/clock.go": "package clock\n\nimport \"time\"\n\nvar now = time.Now\n",
		"src/internal/io/allowlist.txt":  "# kept until proc lands\nsrc/a/kept.go os/exec\nsrc/a/hub.go os/exec\n",
		"src/a/broken.go":                "not go",
	}))
	same(t, found, []string{
		"src/a/clock.go:5: io-module: time.Now reaches the clock around its door (src/internal/io/clock)",
		"src/a/clock.go:7: io-module: time.Sleep reaches the clock around its door",
		"src/a/clock.go:7: io-module: time.After reaches the clock around its door",
		"src/a/disk.go:5: io-module: os.ReadFile reaches the disk around its door (src/internal/io/disk)",
		// Its os/exec is allowed for now; gh is GitHub's door's alone.
		"src/a/hub.go:5: io-module: gh reaches GitHub around its door (src/internal/io/github); go through it",
		"src/a/net.go:3: io-module: net/http reaches the network around its door (src/internal/io/http)",
		"src/a/proc.go:3: io-module: os/exec reaches processes around its door (src/internal/io/proc)",
		// An import a door owns covers its subpackages.
		"src/a/sub.go:3: io-module: github.com/google/go-github/v60/github reaches GitHub around its door",
	})
}

func TestAWalkOrGlobOutsideTheDiskModuleIsRefused(t *testing.T) {
	t.Parallel()
	found := check(t, "io-module", withDoors(map[string]string{
		"src/a/walk.go":             "package a\n\nimport \"path/filepath\"\n\nfunc f() { _ = filepath.WalkDir(\".\", nil) }\n",
		"src/a/both.go":             "package a\n\nimport fp \"path/filepath\"\n\nfunc f() { _ = fp.Walk(\".\", nil); _, _ = fp.Glob(\"*\") }\n",
		"src/a/pure.go":             "package a\n\nimport \"path/filepath\"\n\nvar p = filepath.Join(\"a\", \"b\")\n",
		"src/internal/io/disk/d.go": "package disk\n\nimport \"path/filepath\"\n\nfunc f() { _ = filepath.WalkDir(\".\", nil) }\n",
	}))
	same(t, found, []string{
		"src/a/both.go:5: io-module: path/filepath.Glob reaches the disk",
		"src/a/both.go:5: io-module: path/filepath.Walk reaches the disk",
		"src/a/walk.go:5: io-module: path/filepath.WalkDir reaches the disk",
	})
}

func TestTextABoxIsToldToRunGoesThroughTheDoor(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name, path, text string
		want             []string
	}{
		{
			"an agent running gh", "src/plugin/agents/a.md", "# A\n\nRun `gh pr view 5` for the state.\n",
			[]string{"src/plugin/agents/a.md:3: io-module: gh reaches GitHub around its door (src/internal/io/github); go through se"},
		},
		{
			"a skill calling the API by URL", "src/plugin/skills/s/SKILL.md", "curl https://api.github.com/repos/x/y\n",
			[]string{"src/plugin/skills/s/SKILL.md:1: io-module: api.github.com reaches GitHub around its door"},
		},
		{
			"a hook naming a GitHub MCP tool", "src/plugin/hooks/h.ts", "allow('mcp__github__create_pull_request')\n",
			[]string{"src/plugin/hooks/h.ts:1: io-module: mcp__github__create_pull_request reaches GitHub around its door"},
		},
		{"a script", "src/scripts/x.sh", "#!/bin/sh\ngh issue list\n", []string{"src/scripts/x.sh:2: io-module: gh reaches GitHub"}},
		{"the battery's shell", "tests/x.sh", "x=$(gh api user)\n", []string{"tests/x.sh:1: io-module: gh reaches GitHub"}},
		{"CLAUDE.md", "CLAUDE.md", "# How\n\nOpen the PR with gh.\n", []string{"CLAUDE.md:3: io-module: gh reaches GitHub"}},
		{"a word that holds gh", "src/plugin/agents/a.md", "a ghost, the gh-calls script, gh_2.0_linux and $GH\n", nil},
		{"a file no box is told to run", "spec/x.md", "Run gh.\n", nil},
		{"a marked line", "src/plugin/agents/a.md", "Never run gh. <!-- se: around-the-door - forbids the bypass -->\n", nil},
		{"a marker without a reason", "src/plugin/agents/a.md", "Run gh. se: around-the-door\n", []string{
			"src/plugin/agents/a.md:1: io-module: gh reaches GitHub",
			"src/plugin/agents/a.md:1: io-module: the marker gives no reason",
		}},
		{
			"a marker on a line that goes around nothing", "tests/x.sh", "echo hi # se: around-the-door - why\n",
			[]string{"tests/x.sh:1: io-module: the marker passes nothing"},
		},
		{"a marked Go line", "src/a/a.go", "package a\n\nimport \"os/exec\" // se: around-the-door - a reason\n", nil},
		{"a Go marker without a reason", "src/a/a.go", "package a\n\nimport \"os/exec\" // se: around-the-door\n", []string{
			"src/a/a.go:3: io-module: os/exec reaches processes",
			"src/a/a.go:3: io-module: the marker gives no reason",
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			t.Parallel()
			same(t, check(t, "io-module", withDoors(map[string]string{c.path: c.text})), c.want)
		})
	}
}

func TestEveryDoorDeclaresWhatItGuards(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name  string
		files map[string]string
		want  []string
	}{
		{
			"a door without its declaration",
			map[string]string{"src/internal/io/bare/b.go": "package bare\n", "src/internal/io/bare/a.go": "package bare\n"},
			[]string{"src/internal/io/bare/a.go:1: io-module: the I/O module src/internal/io/bare declares nothing: write src/internal/io/bare/owns.yaml"},
		},
		{
			"a declaration that says no resource",
			map[string]string{"src/internal/io/x/owns.yaml": "go: []\n"},
			[]string{"src/internal/io/x/owns.yaml:1: io-module: it says no resource it guards"},
		},
		{
			"a key no declaration takes",
			map[string]string{"src/internal/io/x/owns.yaml": "guards: \"x: y\"\nfiles: [a.go]\n"},
			[]string{"src/internal/io/x/owns.yaml:1: io-module: owns.yaml reads as no declaration"},
		},
		{
			"a name that is no Go name",
			map[string]string{"src/internal/io/x/owns.yaml": "guards: \"x: y\"\ngo: [Not A Name]\n"},
			[]string{"src/internal/io/x/owns.yaml:1: io-module: Not A Name reads as no Go import or package member"},
		},
		{
			"a word that is no command word",
			map[string]string{"src/internal/io/x/owns.yaml": "guards: \"x: y\"\ncommands: [\"gh pr\"]\n"},
			[]string{"src/internal/io/x/owns.yaml:1: io-module: gh pr reads as no command word"},
		},
		{"a name two doors own", map[string]string{"src/internal/io/zz/owns.yaml": "guards: \"z: z\"\ngo: [os/exec]\ncommands: [gh]\n"}, []string{
			"src/internal/io/zz/owns.yaml:1: io-module: os/exec is src/internal/io/proc's already",
			"src/internal/io/zz/owns.yaml:1: io-module: gh is src/internal/io/github's already",
		}},
		{"the allowlist beside the doors is no door", map[string]string{"src/internal/io/allowlist.txt": "# nothing\n"}, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			t.Parallel()
			same(t, check(t, "io-module", withDoors(c.files)), c.want)
		})
	}
}

func TestTheIOAllowlistOnlyShrinks(t *testing.T) {
	t.Parallel()
	found := check(t, "io-module", withDoors(map[string]string{
		"src/a/kept.go":   "package a\n\nimport \"os/exec\"\n\nvar _ = exec.Command\n",
		"src/a/done.go":   "package a\n\nimport \"time\"\n\nvar d = time.Second\n",
		"src/a/marked.go": "package a\n\nimport \"os/exec\" // se: around-the-door - a reason\n",
		"tests/kept.sh":   "gh auth status\n",
		"tests/done.sh":   "echo done\n",
		"src/internal/io/allowlist.txt": "# a comment\n\nsrc/a/kept.go os/exec\nsrc/a/kept.go os/exec\nsrc/a/done.go time.Now\nsrc/a/gone.go os/exec\njust-one-word\n" +
			"tests/kept.sh gh\ntests/done.sh gh\nsrc/a/marked.go os/exec\n",
	}))
	same(t, found, []string{
		"src/internal/io/allowlist.txt:4: io-module: the entry is named twice",
		"src/internal/io/allowlist.txt:5: io-module: the entry matches nothing: src/a/done.go no longer reaches time.Now",
		"src/internal/io/allowlist.txt:6: io-module: the entry names no such file: src/a/gone.go",
		"src/internal/io/allowlist.txt:7: io-module: an entry is a file and what it reaches",
		"src/internal/io/allowlist.txt:9: io-module: the entry matches nothing: tests/done.sh no longer reaches gh",
		// A marked line passes on its own; the entry passes nothing more.
		"src/internal/io/allowlist.txt:10: io-module: the entry matches nothing: src/a/marked.go no longer reaches os/exec",
	})
}

// same fails unless found holds exactly one finding starting with each of want.
func same(t *testing.T, found, want []string) {
	t.Helper()
	if len(found) != len(want) {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
	for _, w := range want {
		hit := false
		for _, f := range found {
			hit = hit || strings.HasPrefix(f, w)
		}
		if !hit {
			t.Errorf("missing %q in:\n%s", w, strings.Join(found, "\n"))
		}
	}
}
