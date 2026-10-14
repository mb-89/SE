// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// refreshPull is PR n on issue-<n/10> at head sha, as GitHub lists it.
func refreshPull(n int, sha, state string, autoMerge bool) string {
	am := "null"
	if autoMerge {
		am = `{"merge_method":"squash"}`
	}
	return fmt.Sprintf(`{"number":%d,"mergeable":%v,"mergeable_state":%q,"auto_merge":%s,"head":{"ref":"issue-%d","sha":%q}}`,
		n, state != "dirty", state, am, n/10, sha)
}

// mainPullsPath is the open PRs into main, which Refresh reads.
const mainPullsPath = "repos/o/r/pulls?base=main&state=open&per_page=100"

// refreshGH answers by path; a path with several answers gives them in turn
// and then keeps the last. It records every write, and fails those in fail.
func refreshGH(t *testing.T, answers map[string][]string, fail map[string]string) (GH, *[]string) {
	t.Helper()
	var writes []string
	return func(args ...string) ([]byte, error) {
		path := args[len(args)-1]
		if args[1] == "-X" {
			writes = append(writes, strings.Join(args[1:], " "))
			if msg, ok := fail[path]; ok {
				return nil, errors.New(msg)
			}
			return []byte(`{}`), nil
		}
		as := answers[path]
		if len(as) == 0 {
			t.Fatalf("gh %v was not recorded", args)
		}
		if len(as) > 1 {
			answers[path] = as[1:]
		}
		return []byte(as[0]), nil
	}, &writes
}

func TestRefreshUpdatesTheAutoMergePRsBehindMain(t *testing.T) {
	c := atNow()
	gh, writes := refreshGH(t, map[string][]string{
		mainPullsPath: {"[" + strings.Join([]string{
			refreshPull(10, "a1", "", true),      // behind: updated
			refreshPull(20, "b1", "", true),      // up to date
			refreshPull(30, "c1", "", false),     // auto-merge off
			refreshPull(40, "d1", "dirty", true), // conflicts
		}, ",") + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":2}`},
		"repos/o/r/compare/main...b1?per_page=1": {`{"behind_by":0}`},
		"repos/o/r/compare/main...d1?per_page=1": {`{"behind_by":1}`},
		// Asked for its mergeability, then twice for its new head.
		"repos/o/r/pulls/10": {refreshPull(10, "a1", "behind", true), refreshPull(10, "a1", "behind", true), refreshPull(10, "a2", "blocked", true)},
		"repos/o/r/pulls/40": {refreshPull(40, "d1", "dirty", true)},
	}, nil)
	got, err := Source{Repo: repo, GH: gh, Clock: c}.Refresh()
	if err != nil {
		t.Fatal(err)
	}
	want := []Refreshed{
		{PR: 10, Branch: "issue-1", Head: "a2", Did: "merged main in at a2 and started ci.yml"},
		{PR: 40, Branch: "issue-4", Head: "d1", Did: "left to its takeover: it conflicts with main"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v", got)
	}
	if want := []string{
		"-X PUT -f expected_head_sha=a1 repos/o/r/pulls/10/update-branch",
		"-X POST -f ref=issue-1 repos/o/r/actions/workflows/ci.yml/dispatches",
	}; !reflect.DeepEqual(*writes, want) {
		t.Fatalf("writes %q", *writes)
	}
	if waited := c.Now().Sub(now); waited != 2*pause {
		t.Fatalf("waited %s", waited)
	}
}

func TestRefreshReportsAFailedUpdateAndGoesOn(t *testing.T) {
	gh, writes := refreshGH(t, map[string][]string{
		mainPullsPath:                            {"[" + refreshPull(10, "a1", "", true) + "," + refreshPull(20, "b1", "", true) + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/compare/main...b1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/pulls/10":                     {refreshPull(10, "a1", "behind", true)},
		"repos/o/r/pulls/20":                     {refreshPull(20, "b1", "behind", true), refreshPull(20, "b2", "blocked", true)},
	}, map[string]string{"repos/o/r/pulls/10/update-branch": "gh: merge conflict between base and head (HTTP 422)"})
	got, err := Source{Repo: repo, GH: gh, Clock: atNow()}.Refresh()
	if err == nil || !strings.Contains(err.Error(), "could not bring PR #10 up to date with main") {
		t.Fatalf("%v", err)
	}
	if len(got) != 2 || !strings.Contains(got[0].Did, "failed: gh: merge conflict") || got[1].Head != "b2" {
		t.Fatalf("got %+v", got)
	}
	if len(*writes) != 3 {
		t.Fatalf("writes %q", *writes)
	}
}

func TestRefreshSaysWhenTheHeadNeverMoves(t *testing.T) {
	gh, writes := refreshGH(t, map[string][]string{
		mainPullsPath:                            {"[" + refreshPull(10, "a1", "", true) + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/pulls/10":                     {refreshPull(10, "a1", "behind", true)},
	}, nil)
	got, err := Source{Repo: repo, GH: gh, Clock: atNow()}.Refresh()
	if err == nil || len(got) != 1 || !strings.Contains(got[0].Failed, "head is still a1") {
		t.Fatalf("%+v %v", got, err)
	}
	// No CI was started on the old head.
	if len(*writes) != 1 {
		t.Fatalf("writes %q", *writes)
	}
}
