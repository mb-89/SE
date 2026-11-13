package host_test

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/kern/bus"
	"github.com/mb-89/kern/host"
	"github.com/mb-89/kern/index"
)

// The conservative parsing: an ordinary command names no script, and a script
// named by its path, run directly or by an interpreter, is found and resolved
// against the directory a cd before it left.
func TestOnlyAScriptNamedByItsPathIsARun(t *testing.T) {
	t.Parallel()
	dir := filepath.FromSlash("/work")
	none := []string{
		"git status",
		"git -C /work log --oneline -3",
		"uv run pytest -q tests/test_retro.py",
		"uv run python -m pytest -q",
		"python -c 'print(1)'",
		"go test ./...",
		"go vet ./... && go test ./host/",
		"ls -la scripts/",
		"cat scripts/x.py | head",
		"echo ./x.sh",
		"grep -rn foo scripts/ # ./x.sh",
		"python $SCRIPT",
		"bash -c './x.sh'",
		"uv run --with rich python -m rich",
		"node --version",
		"",
	}
	for _, cmd := range none {
		if got := host.ScriptsRun(cmd, dir); len(got) != 0 {
			t.Errorf("%q runs %v, and wants no script", cmd, got)
		}
	}
	some := map[string][]string{
		"./x.sh":                                     {"/work/x.sh"},
		"bash x.sh a b":                              {"/work/x.sh"},
		"python3 -I /tmp/s/probe.py --flag":          {"/tmp/s/probe.py"},
		"cd /else && uv run python tools/a.py":       {"/else/tools/a.py"},
		"uv run --with rich a.py":                    {"/work/a.py"},
		"FOO=1 env python 'my dir/b.py' > out.txt":   {"/work/my dir/b.py"},
		"go run ./gen.go":                            {"/work/gen.go"},
		"node c.js; ./d.sh | tee log":                {"/work/c.js", "/work/d.sh"},
		"pwsh -NoProfile -File scripts/e.ps1":        {"/work/scripts/e.ps1"},
		"uv run python scripts/work_tickets.py sync": {"/work/scripts/work_tickets.py"},
	}
	for cmd, want := range some {
		got := host.ScriptsRun(cmd, dir)
		if len(got) != len(want) {
			t.Errorf("%q runs %v, and wants %v", cmd, got, want)
			continue
		}
		for i := range want {
			if got[i] != filepath.FromSlash(want[i]) {
				t.Errorf("%q runs %v, and wants %v", cmd, got, want)
			}
		}
	}
}

func git(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "maintenance.auto=false",
		"-c", "user.name=alice", "-c", "user.email=alice@example.com"}, args...)...)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
}

// An untracked script run three times through the hook path is counted three
// times under its path and content hash, never with its arguments; a tracked
// script, an ignored one and an ordinary command are not counted.
func TestAnUntrackedScriptsRunsAreCounted(t *testing.T) {
	t.Parallel()
	root := t.TempDir()
	git(t, root, "init", "-q")
	write := func(rel, text string) {
		p := filepath.Join(root, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, []byte(text), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	write("scripts/tracked.py", "print('tracked')\n")
	write(".gitignore", "build/\n")
	git(t, root, "add", ".")
	git(t, root, "commit", "-q", "-m", "tracked")
	write("probe.py", "print('ad hoc')\n")
	write("build/gen.sh", "echo ignored\n")

	c := served(t, host.Options{Root: root, Clock: newClock(), Wiring: index.Wiring{}})
	client := as(t, c, bus.Client)
	post := func(command string) {
		var effect host.HookAnswer
		ask(t, client, bus.Hook+host.PostToolUse, map[string]any{"session_id": "s1", "cwd": root,
			"tool_name": "Bash", "tool_input": map[string]string{"command": command}}, &effect)
	}
	post("uv run python scripts/tracked.py")
	post("bash build/gen.sh")
	post("git status && uv run pytest -q")
	for _, arg := range []string{"one", "two", "secret-three"} {
		post("python probe.py " + arg)
	}
	// The next event is handled once the last count is written (core.go hook).
	var effect host.HookAnswer
	ask(t, client, bus.Hook+"UserPromptSubmit", map[string]string{"session_id": "s1"}, &effect)

	records := uses(t, root)
	if len(records) != 3 {
		t.Fatalf("the use log holds %d records, and wants three (the untracked script's runs): %v", len(records), records)
	}
	for _, r := range records {
		if r["script"] != "probe.py" || r["session"] != "s1" || len(r["hash"].(string)) != 64 {
			t.Fatalf("the run record is %v, and wants probe.py with its sha256 in session s1", r)
		}
		if data, _ := json.Marshal(r); containsAny(string(data), "one", "two", "secret") {
			t.Fatalf("the run record %s names the command's arguments", data)
		}
	}
}

func containsAny(s string, subs ...string) bool {
	for _, sub := range subs {
		if strings.Contains(s, sub) {
			return true
		}
	}
	return false
}
