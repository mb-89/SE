// Internal test package: package main cannot be imported.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// prose makes a git workspace holding files, and answers its folder.
func prose(t *testing.T, files map[string]string) string {
	t.Helper()
	ws := filepath.FromSlash("/ws")
	for p, text := range files {
		put(t, onFake(t), filepath.Join(ws, filepath.FromSlash(p)), text)
	}
	git(t, ws, "init", "-q")
	return ws
}

const skill = "---\nname: work\ndescription: Take the next issue.\n---\n\n# Work\n\nReader: the agent running it.\n"

func TestTheManifestsAreMadeFromTheirOwners(t *testing.T) {
	t.Parallel()
	ws := prose(t, map[string]string{
		"src/plugin/skills/work/SKILL.md": skill,
		"spec/issues.md":                  "# Issues: how the fleet works\n\nReader: whoever changes it.\n",
		"spec/models.yaml":                "box: opus\n",
		"spec/deep/x.md":                  "# Not listed\n",
	})
	code, out, errs := se(t, "--workspace", ws, "manifest", "spec")
	if want := "- [spec/issues.md](spec/issues.md): Issues: how the fleet works\n- [spec/models.yaml](spec/models.yaml)\n"; code != 0 || out != want {
		t.Fatalf("spec (exit %d): %q %s", code, out, errs)
	}
	_, out, _ = se(t, "--workspace", ws, "manifest", "skills")
	if want := "- [`se:work`](src/plugin/skills/work/SKILL.md): Take the next issue.\n"; out != want {
		t.Fatalf("skills: %q", out)
	}
	// The agents come from the registry of kinds, and each must have its file.
	if code, _, errs := se(t, "--workspace", ws, "manifest", "agents"); code != 1 || !strings.Contains(errs, "the leaf kind's agent has no file src/plugin/agents/worker.md") {
		t.Fatalf("agents without their files (exit %d): %s", code, errs)
	}
	// With this checkout's agent files in place, each is listed.
	agents, err := filepath.Glob(filepath.Join("..", "..", "plugin", "agents", "*.md"))
	if err != nil || len(agents) == 0 {
		t.Fatalf("this checkout's agents: %v %v", agents, err)
	}
	for _, a := range agents {
		text, err := os.ReadFile(a)
		if err != nil {
			t.Fatal(err)
		}
		put(t, onFake(t), filepath.Join(ws, "src", "plugin", "agents", filepath.Base(a)), string(text))
	}
	_, out, _ = se(t, "--workspace", ws, "manifest", "agents")
	if !strings.HasPrefix(out, "- [`se:worker`](src/plugin/agents/worker.md), for the kind leaf: ") || strings.Count(out, "\n") != 5 {
		t.Fatalf("agents: %q", out)
	}
	_, out, _ = se(t, "--workspace", ws, "manifest", "checks")
	if !strings.Contains(out, "- `ci`: every merged PR had green CI (the last run of each check on its head); checked from the first commit.\n") ||
		!strings.Contains(out, "; checked on what was created after PR #91 brought it.\n") ||
		!strings.Contains(out, "; checked on what closed after PR #74 brought it.\n") {
		t.Fatalf("checks: %q", out)
	}
	_, out, _ = se(t, "--workspace", ws, "manifest", "usage", "fleet", "rules")
	if want := "```\nse fleet check [--json] [--repo OWNER/NAME]\nse fleet fix [--json] [--repo OWNER/NAME]\nse fleet prune [--apply] [--json] [--repo OWNER/NAME]\nse fleet refresh [--json] [--repo OWNER/NAME]\nse fleet rules [--json] [--repo OWNER/NAME]\nse rules\n```\n"; out != want {
		t.Fatalf("usage: %q", out)
	}
	if code, _, errs := se(t, "--workspace", ws, "manifest", "frob"); code != 1 || !strings.Contains(errs, `no manifest "frob"`) {
		t.Fatalf("an unknown manifest (exit %d): %s", code, errs)
	}
}

func TestWriteFillsEveryManifestAndTheRulesHoldItThere(t *testing.T) {
	t.Parallel()
	readme := "# SE\n\nReader: a person meeting SE.\n\n<!-- se:manifest skills -->\n<!-- /se:manifest -->\n"
	ws := prose(t, map[string]string{
		"README.md":                       readme,
		"spec/a.md":                       "# A\n\nReader: whoever.\n\n<!-- se:manifest skills -->\nstale\n<!-- /se:manifest -->\n",
		"src/plugin/skills/work/SKILL.md": skill,
	})
	if code, _, errs := se(t, "--workspace", ws, "rules"); code != 1 || !strings.Contains(errs, `README.md:5: manifest: manifest "skills" differs`) ||
		!strings.Contains(errs, `spec/a.md:5: manifest: manifest "skills" differs`) {
		t.Fatalf("rules before the write (exit %d): %s", code, errs)
	}
	if code, out, errs := se(t, "--workspace", ws, "manifest", "--write"); code != 0 || out != "rewrote README.md, spec/a.md\n" {
		t.Fatalf("write (exit %d): %q %s", code, out, errs)
	}
	data, _ := onFake(t).ReadFile(filepath.Join(ws, "spec", "a.md"))
	if !strings.Contains(string(data), "- [`se:work`](../src/plugin/skills/work/SKILL.md): Take the next issue.\n<!-- /se:manifest -->") {
		t.Fatalf("spec/a.md links from its own folder:\n%s", data)
	}
	if code, out, errs := se(t, "--workspace", ws, "rules"); code != 0 || !strings.Contains(out, "check: rule manifest took") {
		t.Fatalf("rules after the write (exit %d): %s %s", code, out, errs)
	}
	if _, out, _ := se(t, "--workspace", ws, "manifest", "--write"); out != "every manifest is current\n" {
		t.Fatalf("a second write: %q", out)
	}
}

func TestTheRulesKnowSesCommands(t *testing.T) {
	t.Parallel()
	ws := prose(t, map[string]string{
		"README.md": "# SE\n\nReader: a person meeting SE.\n\nRun `se issue pull --take`, not `se issue pull --tak` or `se issue take`.\n",
	})
	code, _, errs := se(t, "--workspace", ws, "rules")
	if code != 1 || !strings.Contains(errs, "README.md:5: se-command: se issue pull takes no flag --tak") ||
		!strings.Contains(errs, `README.md:5: se-command: se has no command "issue take"`) || strings.Count(errs, "se-command: ") != 2 {
		t.Fatalf("rules (exit %d): %s", code, errs)
	}
}

func TestAFolderGitIgnoresCountsThoughNoCheckoutHoldsIt(t *testing.T) {
	t.Parallel()
	ws := prose(t, map[string]string{
		".gitignore": "a/bin/\n",
		"a/x.md":     "# X\n\nReader: anyone.\n",
		"README.md":  "# SE\n\nReader: a person meeting SE.\n\n`a/bin` and `a/bin/se` are built; `a/gone` is not.\n",
	})
	code, _, errs := se(t, "--workspace", ws, "rules")
	if code != 1 || !strings.Contains(errs, "README.md:5: repo-path: no such path: a/gone") || strings.Count(errs, "repo-path: ") != 1 {
		t.Fatalf("rules (exit %d): %s", code, errs)
	}
}

func TestAManifestReadsItsOwnersFromTheDisk(t *testing.T) {
	t.Parallel()
	d, root := disk.NewFake(), filepath.FromSlash("/checkout")
	put(t, d, filepath.Join(root, "spec", "issues.md"), "# Issues: how the fleet works\n")
	put(t, d, filepath.Join(root, "src", "plugin", "skills", "work", "SKILL.md"), skill)
	paths := []string{"spec/issues.md", "spec/models.yaml", "src/plugin/skills/work/SKILL.md"}
	got, err := manifest(d, root, paths, "spec", "README.md")
	if want := "- [spec/issues.md](spec/issues.md): Issues: how the fleet works\n- [spec/models.yaml](spec/models.yaml)"; err != nil || got != want {
		t.Fatalf("spec: %q %v", got, err)
	}
	got, err = manifest(d, root, paths, "skills", "spec/a.md")
	if want := "- [`se:work`](../src/plugin/skills/work/SKILL.md): Take the next issue."; err != nil || got != want {
		t.Fatalf("skills: %q %v", got, err)
	}
	if err := d.Remove(filepath.Join(root, "src", "plugin", "skills", "work", "SKILL.md")); err != nil {
		t.Fatal(err)
	}
	if _, err := manifest(d, root, paths, "skills", "README.md"); err == nil {
		t.Fatal("a skill gone from the disk was listed")
	}
}

func TestTheRulesSeeWhatGitTracksAndIgnores(t *testing.T) {
	t.Parallel()
	m := proc.NewFake()
	m.Install("git", func(c proc.Cmd) int {
		args := strings.Join(c.Args, " ")
		switch {
		case c.Dir != "/ws":
			return 128
		case args == "ls-files -z --cached --others --exclude-standard":
			_, _ = fmt.Fprint(c.Stdout, "README.md\x00a/x.md\x00")
			return 0
		case args == "check-ignore -q --no-index "+filepath.FromSlash("a/bin/"):
			return 0
		}
		return 1
	})
	repo, err := repoOf(disk.NewFake(), m, "/ws")
	if err != nil || strings.Join(repo.Paths, " ") != "README.md a/x.md" {
		t.Fatalf("%v %v", repo, err)
	}
	if !repo.Ignored("a/bin") || repo.Ignored("a/gone") {
		t.Fatal("the rules see a/bin, a folder git ignores only as a folder, as kept, or a/gone as ignored")
	}
}
