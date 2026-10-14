// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// asBox makes the test's session a box: a cloud session no person attends.
func asBox(t *testing.T) {
	t.Helper()
	setenv(t, "CLAUDE_CODE_REMOTE", "true")
	setenv(t, "CLAUDE_CODE_SESSION_ATTENDED", "0")
}

// stopWorld is a box in /ws that took #3, GitHub answering a's paths, and
// the Stop hook capped at 2 refusals in a row.
func stopWorld(t *testing.T, a map[string]string) *disk.Fake {
	t.Helper()
	asBox(t)
	d := onFake(t)
	put(t, d, "/ws/.se/.runtime/box.json", `{"issues":[3]}`)
	put(t, d, "/ws/"+StopPath, "refusals: 2\n")
	hubAt(t, a)
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
	t.Parallel()
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

func TestOnlyAMergedPROrASupersedeLetsTheBoxEnd(t *testing.T) {
	t.Parallel()
	stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[{"number":9,"html_url":"p9","auto_merge":null}]`})
	if v := stops(t); !strings.Contains(v.Block, "PR #9 (p9) has auto-merge off") {
		t.Fatalf("%+v", v)
	}
	// A box keeps its PR until it merges: auto-merge on is not the end.
	hubAt(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`})
	if v := stops(t); !strings.Contains(v.Block, "PR #9 (p9) has not merged") || !strings.Contains(v.Block, "se issue keep") {
		t.Fatalf("%+v", v)
	}
	// Merged, its PR closed the issue.
	hubAt(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"closed"}`})
	if v := stops(t); v.Block != "" || v.Pass == "" {
		t.Fatalf("%+v", v)
	}
	// A superseded issue is closed.
	hubAt(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"closed"}`})
	if v := stops(t); v.Block != "" || v.Pass == "" {
		t.Fatalf("%+v", v)
	}
}

func TestALandRecordCountsAsAutoMergeOn(t *testing.T) {
	t.Parallel()
	// GitHub shows the PR with auto-merge unset, as a proxy's route may leave it.
	d := stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[{"number":9,"html_url":"p9","auto_merge":null}]`})
	if v := stops(t); !strings.Contains(v.Block, "auto-merge off") {
		t.Fatalf("%+v", v)
	}
	// The sub-agent landed #3 in its worktree beside the box's checkout: its
	// auto-merge is on, and the box keeps the PR until it merges.
	put(t, d, "/issue-3/.se/.runtime/box.json", `{"landed":{"3":{"pr":9,"auto_merge":true}}}`)
	if v := stops(t); !strings.Contains(v.Block, "PR #9 (p9) has not merged") {
		t.Fatalf("%+v", v)
	}
	// A leaf's sub-agent is judged by the same record (the count afresh).
	put(t, d, "/ws/.se/.runtime/box.json", `{"issues":[3]}`)
	put(t, d, "/t/leaf.jsonl", `{"type":"user","message":{"content":"Work on se issue #3 in the worktree /issue-3, on its branch issue-3."}}`+"\n")
	if v := stops(t, "--agent-transcript", "/t/leaf.jsonl"); !strings.Contains(v.Block, "has not merged") {
		t.Fatalf("%+v", v)
	}
	// A record in the box's own workspace counts too; a record without
	// auto-merge does not.
	put(t, d, "/issue-3/.se/.runtime/box.json", `{}`)
	put(t, d, "/ws/.se/.runtime/box.json", `{"issues":[3],"landed":{"3":{"pr":9,"auto_merge":false}}}`)
	if v := stops(t); !strings.Contains(v.Block, "auto-merge off") {
		t.Fatalf("%+v", v)
	}
	put(t, d, "/ws/.se/.runtime/box.json", `{"issues":[3],"landed":{"3":{"pr":9,"auto_merge":true}}}`)
	if v := stops(t); !strings.Contains(v.Block, "has not merged") {
		t.Fatalf("%+v", v)
	}
	// Merged, the issue is closed.
	hubAt(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"closed"}`})
	if v := stops(t); v.Block != "" {
		t.Fatalf("%+v", v)
	}
}

func TestAnInteractiveSessionIsNeverRefused(t *testing.T) {
	t.Parallel()
	stopWorld(t, map[string]string{"repos/o/r/issues/3": `{"number":3,"state":"open"}`, pulls3: `[]`})
	setenv(t, "CLAUDE_CODE_SESSION_ATTENDED", "1")
	for range 5 {
		if v := stops(t); v.Block != "" || !strings.Contains(v.Pass, "interactive") {
			t.Fatalf("%+v", v)
		}
	}
}

func TestABoxWaitingOnBackgroundWorkOrWithoutATakePasses(t *testing.T) {
	t.Parallel()
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
	t.Parallel()
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
	t.Parallel()
	d := stopWorld(t, map[string]string{})
	if v := stops(t); v.Block != "" || !strings.Contains(v.Pass, "the check is broken") {
		t.Fatalf("%+v", v)
	}
	if log, err := d.ReadFile(filepath.FromSlash("/ws/.se/.runtime/logs/stop.log")); err != nil || !strings.Contains(string(log), "unjudged on #3") {
		t.Fatalf("%q %v", log, err)
	}
}

func TestATakeRecordsTheIssueForTheStopHook(t *testing.T) {
	t.Parallel()
	d := onFake(t)
	c := &Call{Workspace: "/ws", World: World{Disk: d}}
	if err := recordTake(c, 3); err != nil {
		t.Fatal(err)
	}
	if b := readBox(c); !slices.Equal(b.Issues, []int{3}) || len(b.Refused) != 0 {
		t.Fatalf("%+v", b)
	}
	// A box takes several issues; it keeps every one, each once.
	for _, n := range []int{4, 3} {
		if err := recordTake(c, n); err != nil {
			t.Fatal(err)
		}
	}
	if b := readBox(c); !slices.Equal(b.Issues, []int{3, 4}) {
		t.Fatalf("%+v", b)
	}
	// A later take keeps the PRs landed here before.
	if err := recordLand(c, 3, 9); err != nil {
		t.Fatal(err)
	}
	if err := recordTake(c, 5); err != nil {
		t.Fatal(err)
	}
	if b := readBox(c); !slices.Equal(b.Issues, []int{3, 4, 5}) || b.Landed[3] != (landed{PR: 9, AutoMerge: true}) {
		t.Fatalf("%+v", b)
	}
}

func TestABoxIsHeldToEveryIssueItTook(t *testing.T) {
	t.Parallel()
	d := stopWorld(t, map[string]string{
		"repos/o/r/issues/1": `{"number":1,"state":"open"}`,
		"repos/o/r/pulls?head=o:issue-1&base=main&state=open&per_page=100": `[]`,
		"repos/o/r/issues/2": `{"number":2,"state":"open"}`,
		"repos/o/r/pulls?head=o:issue-2&base=main&state=open&per_page=100": `[{"number":9,"html_url":"p9","auto_merge":{"merge_method":"squash"}}]`,
	})
	put(t, d, "/ws/.se/.runtime/box.json", `{"issues":[1,2]}`)
	v := stops(t)
	// #2's PR is up, auto-merge on, but a box keeps it until it merges.
	if !strings.Contains(v.Block, "#1 is open with neither a PR from issue-1 nor a supersede") || !strings.Contains(v.Block, "#2 is open and its PR #9 (p9) has not merged") {
		t.Fatalf("%+v", v)
	}
}

func TestIssueSupersedeReadsItsWords(t *testing.T) {
	t.Parallel()
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
