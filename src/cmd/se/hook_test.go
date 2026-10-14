// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// asBox makes the test's session a box (box true) or an interactive one.
func asBox(t *testing.T, box bool) {
	t.Helper()
	old := boxEnv
	boxEnv = func(k string) string {
		switch {
		case !box:
			return ""
		case k == "CLAUDE_CODE_REMOTE":
			return "true"
		case k == "CLAUDE_CODE_SESSION_ATTENDED":
			return "0"
		}
		return ""
	}
	t.Cleanup(func() { boxEnv = old })
}

// stopWorld is a box in /ws that took #3, GitHub answering a's paths, and
// the Stop hook capped at 2 refusals in a row.
func stopWorld(t *testing.T, a map[string]string) *disk.Fake {
	t.Helper()
	asBox(t, true)
	d := onFake(t)
	put(t, d, "/ws/.se/.runtime/box.json", `{"issue":3}`)
	put(t, d, "/ws/"+StopPath, "refusals: 2\n")
	old := gh
	gh = func(args ...string) ([]byte, error) {
		if v, ok := a[args[len(args)-1]]; ok {
			return []byte(v), nil
		}
		return nil, errors.New("gh: Not Found (HTTP 404)")
	}
	t.Cleanup(func() { gh = old })
	return d
}

const pulls3 = "repos/o/r/pulls?head=o:issue-3&base=main&state=open&per_page=100"

// stops runs se hook stop and answers its verdict.
func stops(t *testing.T, args ...string) verdict {
	t.Helper()
	code, out, errs := se(t, append([]string{"hook", "stop", "--repo", "o/r", "--workspace", "/ws"}, args...)...)
	var v verdict
	if err := json.Unmarshal([]byte(out), &v); code != 0 || err != nil {
		t.Fatalf("exit %d, %q %q: %v", code, out, errs, err)
	}
	return v
}

func TestAClaimWithoutAPRIsRefusedUpToTheCap(t *testing.T) {
	d := stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[]`})
	for k := 1; k <= 2; k++ {
		v := stops(t)
		if !strings.Contains(v.Block, "#3 is open with neither a PR from issue-3 nor a supersede") || !strings.Contains(v.Block, "se issue supersede 3") {
			t.Fatalf("refusal %d: %+v", k, v)
		}
	}
	// The cap lets the turn end and logs why.
	if v := stops(t); v.Block != "" || !strings.Contains(v.Pass, "refused 2 times in a row") {
		t.Fatalf("%+v", v)
	}
	if log, err := d.ReadFile(filepath.FromSlash("/ws/.se/.runtime/logs/stop.log")); err != nil || !strings.Contains(string(log), "refused 2 times in a row") {
		t.Fatalf("%q %v", log, err)
	}
	// A prompt from a person counts afresh.
	if code, _, errs := se(t, "hook", "prompt", "--workspace", "/ws"); code != 0 {
		t.Fatalf("exit %d, %q", code, errs)
	}
	if v := stops(t); v.Block == "" {
		t.Fatalf("%+v", v)
	}
}

func TestAPRWithAutoMergeOrASupersedeLetsTheBoxEnd(t *testing.T) {
	a := map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[{"number":9,"html_url":"p9","auto_merge":null}]`}
	stopWorld(t, a)
	if v := stops(t); !strings.Contains(v.Block, "PR #9 (p9) has auto-merge off") {
		t.Fatalf("%+v", v)
	}
	a[pulls3] = `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`
	if v := stops(t); v.Block != "" || v.Pass == "" {
		t.Fatalf("%+v", v)
	}
	// A superseded issue is closed.
	a[pulls3] = `[]`
	a["repos/o/r/issues/3"] = `{"number":3,"state":"closed"}`
	if v := stops(t); v.Block != "" || v.Pass == "" {
		t.Fatalf("%+v", v)
	}
}

func TestAnInteractiveSessionIsNeverRefused(t *testing.T) {
	stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[]`})
	asBox(t, false)
	for range 5 {
		if v := stops(t); v.Block != "" || !strings.Contains(v.Pass, "interactive") {
			t.Fatalf("%+v", v)
		}
	}
}

func TestABoxWaitingOnBackgroundWorkOrWithoutATakePasses(t *testing.T) {
	d := stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[]`})
	if v := stops(t, "--waiting"); v.Block != "" {
		t.Fatalf("%+v", v)
	}
	put(t, d, "/ws/.se/.runtime/box.json", `{}`)
	if v := stops(t); v.Block != "" || !strings.Contains(v.Pass, "no se issue") {
		t.Fatalf("%+v", v)
	}
}

func TestALeafsSubAgentIsHeldToItsLeaf(t *testing.T) {
	d := stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"closed"}`, "repos/o/r/issues/6": `{"number":6,"state":"open"}`, "repos/o/r/pulls?head=o:issue-6&base=main&state=open&per_page=100": `[]`})
	put(t, d, "/t/leaf.jsonl", `{"type":"user","message":{"content":"Work on se issue #6 in the worktree /issue-6, on its branch issue-6."}}`+"\n")
	put(t, d, "/t/review.jsonl", `{"type":"user","message":{"content":"Review se gate #2 in the worktree /r."}}`+"\n")
	if v := stops(t, "--agent-transcript", "/t/leaf.jsonl"); !strings.Contains(v.Block, "#6 is open") {
		t.Fatalf("%+v", v)
	}
	if v := stops(t, "--agent-transcript", "/t/review.jsonl"); v.Block != "" {
		t.Fatalf("%+v", v)
	}
	// The box itself, its #3 closed, ends.
	if v := stops(t); v.Block != "" {
		t.Fatalf("%+v", v)
	}
}

func TestABrokenCheckLetsTheTurnEndAndLogsWhy(t *testing.T) {
	d := stopWorld(t, map[string]string{})
	if v := stops(t); v.Block != "" || !strings.Contains(v.Pass, "the check is broken") {
		t.Fatalf("%+v", v)
	}
	if log, err := d.ReadFile(filepath.FromSlash("/ws/.se/.runtime/logs/stop.log")); err != nil || !strings.Contains(string(log), "unjudged on #3") {
		t.Fatalf("%q %v", log, err)
	}
}

func TestATakeRecordsTheIssueForTheStopHook(t *testing.T) {
	d := onFake(t)
	c := &Call{Workspace: "/ws", Disk: d}
	if err := recordTake(c, 3); err != nil {
		t.Fatal(err)
	}
	if b := readBox(c); b.Issue != 3 || len(b.Refused) != 0 {
		t.Fatalf("%+v", b)
	}
}

func TestIssueSupersedeReadsItsWords(t *testing.T) {
	for args, want := range map[string]string{
		"":                                 "takes one issue number",
		"3 4 --body q":                     "takes one issue number",
		"3":                                "one of --body and --body-file",
		"3 --body q --body-file f":         "one of --body and --body-file",
		"x --body q":                       "takes one issue number",
		"5 --body q --repo o/r --json=bad": "",
	} {
		code, _, errs := se(t, append([]string{"issue", "supersede", "--repo", "o/r"}, strings.Fields(args)...)...)
		if code != 1 || !strings.Contains(errs, want) {
			t.Errorf("%q: exit %d, %q, want %q", args, code, errs, want)
		}
	}
}
