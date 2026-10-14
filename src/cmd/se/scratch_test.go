// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
)

// TestAProjectHoldingNoSEFileGetsTheHelpTheGuidanceAndATake installs this
// checkout's plugin into a scratch repository that holds no SE file, under a
// Claude configuration of its own, and runs se there as the plugin runs it,
// the checkout named as the plugin names it. The plugin brings its five
// agents and its one skill; /se help names the agents; the session start's
// guidance carries the principles and, in a box, the box's agent; and a take
// on a fake GitHub names its agent.
func TestAProjectHoldingNoSEFileGetsTheHelpTheGuidanceAndATake(t *testing.T) {
	t.Parallel()
	recordedIssues(t)
	// The real claude installs the plugin on the real disk and runs the real
	// git: this test runs on them, as the restart's does.
	w := worldOf(t)
	w.Disk, w.Proc = disk.Real(), proc.Real()
	checkout, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	setenv(t, pluginRepoEnv, checkout)
	root := t.TempDir()
	origin, ws := filepath.Join(root, "origin.git"), filepath.Join(root, "scratch")
	for _, args := range [][]string{
		{root, "init", "-q", "--bare", "-b", "main", origin},
		{root, "clone", "-q", origin, ws},
		{ws, "checkout", "-q", "-b", "main"},
		{ws, "commit", "-q", "--allow-empty", "-m", "start"},
		{ws, "push", "-q", "origin", "main"},
	} {
		if out, err := exec.Command("git", append([]string{"-C", args[0], "-c", "user.name=t", "-c", "user.email=t@t"}, args[1:]...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
	}
	if entries, _ := os.ReadDir(ws); len(entries) != 1 || entries[0].Name() != ".git" {
		t.Fatalf("the scratch repository holds %v", entries)
	}
	// The install, with the scratch configuration's plugins alone, not the
	// ones the session running the test has.
	config := filepath.Join(root, "config")
	claude := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("claude", args...)
		cmd.Dir = ws
		for _, kv := range os.Environ() {
			if !strings.HasPrefix(kv, "CLAUDE_CONFIG_DIR=") && !strings.HasPrefix(kv, "CLAUDE_CODE_PLUGIN_DIRS=") {
				cmd.Env = append(cmd.Env, kv)
			}
		}
		cmd.Env = append(cmd.Env, "CLAUDE_CONFIG_DIR="+config)
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("claude %v: %v\n%s", args, err, out)
		}
		return string(out)
	}
	claude("plugin", "install", "se", "--marketplace", checkout, "--scope", "project", "-y")
	details := claude("plugin", "details", "se")
	agents := regexp.MustCompile(`Agents \(5\) +(.*)`).FindStringSubmatch(details)
	if agents == nil || !regexp.MustCompile(`Skills \(1\) +briefing\n`).MatchString(details) {
		t.Fatalf("the installed plugin's agents and skills:\n%s", details)
	}
	for _, a := range issues.IssueKinds {
		if !strings.Contains(agents[1], a.Agent) {
			t.Errorf("the installed plugin lacks the agent %s:\n%s", a.Agent, details)
		}
	}
	asked := func(words ...string) Reply {
		t.Helper()
		code, out, errs := se(t, append([]string{"--session", "--workspace", ws}, words...)...)
		var r Reply
		if err := json.Unmarshal([]byte(out), &r); err != nil || code != 0 {
			t.Fatalf("%v: exit %d, %q %q", words, code, out, errs)
		}
		return r
	}
	help := asked("help").Text
	for _, want := range []string{"issue pull", "@agent-<name>", "se:worker, se:coordinator, se:reviewer, se:retro, se:overhaul"} {
		if !strings.Contains(help, want) {
			t.Errorf("/se help lacks %q:\n%s", want, help)
		}
	}
	guided := asked("guidance", "--session-id", "s9").Text
	if !strings.Contains(guided, "SE's design principles (spec/principles.md)") || !strings.Contains(guided, "# Design principles") || strings.Contains(guided, "SE box") {
		t.Fatalf("the guidance of a session: %q", guided)
	}
	setenv(t, "CLAUDE_CODE_REMOTE", "true")
	setenv(t, "CLAUDE_CODE_SESSION_ATTENDED", "0")
	boxed := asked("guidance", "--session-id", "s9").Text
	if !strings.Contains(boxed, "This session is an SE box: it is se:coordinator") || !strings.Contains(boxed, "# Coordinator: the box") || strings.Contains(boxed, "name: coordinator") {
		t.Fatalf("the guidance of a box: %q", boxed)
	}
	// The fake take: the box's take names the agent of the issue's kind.
	code, out, errs := se(t, "issue", "pull", "--take", "--worktree", "--json", "--repo", "o/r", "--workspace", ws)
	var took struct {
		Ready    bool   `json:"ready"`
		Agent    string `json:"agent"`
		Worktree string `json:"worktree"`
	}
	if err := json.Unmarshal([]byte(out), &took); err != nil || code != 0 || !took.Ready || took.Agent != "se:worker" || took.Worktree == "" {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	// The repository holds nothing of SE's but the install's settings and what a take keeps at runtime.
	entries, _ := os.ReadDir(ws)
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	if strings.Join(names, " ") != ".claude .git .se" {
		t.Fatalf("the scratch repository holds %v", names)
	}
}
