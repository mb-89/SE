// Internal test package: package main cannot be imported.
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// prose makes a git workspace holding files, and answers its folder.
func prose(t *testing.T, files map[string]string) string {
	t.Helper()
	ws := t.TempDir()
	for p, text := range files {
		full := filepath.Join(ws, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
			t.Fatal(err)
		}
		write(t, full, text)
	}
	if out, err := exec.Command("git", "-C", ws, "init", "-q").CombinedOutput(); err != nil {
		t.Fatalf("git init: %v %s", err, out)
	}
	return ws
}

const skill = "---\nname: work\ndescription: Take the next issue.\n---\n\n# Work\n\nReader: the agent running it.\n"

func TestTheManifestsAreMadeFromTheirOwners(t *testing.T) {
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
	_, out, _ = se(t, "--workspace", ws, "manifest", "usage", "fleet", "rules")
	if want := "```\nse fleet check [--json] [--repo OWNER/NAME]\nse fleet fix [--json] [--repo OWNER/NAME]\nse fleet prune [--apply] [--json] [--repo OWNER/NAME]\nse rules\n```\n"; out != want {
		t.Fatalf("usage: %q", out)
	}
	if code, _, errs := se(t, "--workspace", ws, "manifest", "frob"); code != 1 || !strings.Contains(errs, `no manifest "frob"`) {
		t.Fatalf("an unknown manifest (exit %d): %s", code, errs)
	}
}

func TestWriteFillsEveryManifestAndTheRulesHoldItThere(t *testing.T) {
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
	data, _ := os.ReadFile(filepath.Join(ws, "spec", "a.md"))
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
	ws := prose(t, map[string]string{
		"README.md": "# SE\n\nReader: a person meeting SE.\n\nRun `se issue next --take`, not `se issue next --tak` or `se issue take`.\n",
	})
	code, _, errs := se(t, "--workspace", ws, "rules")
	if code != 1 || !strings.Contains(errs, "README.md:5: se-command: se issue next takes no flag --tak") ||
		!strings.Contains(errs, `README.md:5: se-command: se has no command "issue take"`) || strings.Count(errs, "se-command: ") != 2 {
		t.Fatalf("rules (exit %d): %s", code, errs)
	}
}

func TestAFolderGitIgnoresCountsThoughNoCheckoutHoldsIt(t *testing.T) {
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

func TestWriteRefusesWhileTheIndexHoldsAConflict(t *testing.T) {
	readme := "# SE\n\nReader: a person meeting SE.\n\n<!-- se:manifest spec -->\n<!-- /se:manifest -->\n"
	ws := prose(t, map[string]string{
		"README.md":      readme,
		"spec/issues.md": "# Issues\n\nReader: whoever.\n",
	})
	// Each call names its committer: a runner without a global identity
	// would refuse the merge before it reached the conflict.
	gitOut := func(args ...string) ([]byte, error) {
		return exec.Command("git", append([]string{"-C", ws, "-c", "user.name=se", "-c", "user.email=se@example.com"}, args...)...).CombinedOutput()
	}
	git := func(args ...string) {
		t.Helper()
		if out, err := gitOut(args...); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	git("add", ".")
	git("commit", "-q", "-m", "base")
	git("checkout", "-q", "-b", "other")
	write(t, filepath.Join(ws, "spec", "issues.md"), "# Issues: theirs\n\nReader: whoever.\n")
	git("commit", "-q", "-am", "theirs")
	git("checkout", "-q", "-")
	write(t, filepath.Join(ws, "spec", "issues.md"), "# Issues: ours\n\nReader: whoever.\n")
	git("commit", "-q", "-am", "ours")
	if out, err := gitOut("merge", "-q", "other"); err == nil || !strings.Contains(string(out), "CONFLICT") {
		t.Fatalf("the merge did not conflict: %v %s", err, out)
	}
	code, out, errs := se(t, "--workspace", ws, "manifest", "--write")
	if code != 1 || !strings.Contains(errs, "unmerged paths (spec/issues.md)") {
		t.Fatalf("write during a conflict (exit %d): %q %s", code, out, errs)
	}
	if data, _ := os.ReadFile(filepath.Join(ws, "README.md")); string(data) != readme {
		t.Fatalf("README.md changed:\n%s", data)
	}
}
