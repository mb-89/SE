// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
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

// refreshGH is a fake GitHub seeded from answers on the clock c, each path's
// answers holding one pause after another: GitHub merges main into a PR's
// branch on its own time, and its new head shows later.
func refreshGH(t *testing.T, c *clock.Fake, answers map[string][]string) *github.Fake {
	t.Helper()
	gh := recordedAt(t, c, nil)
	paths := make([]string, 0, len(answers))
	for path := range answers {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	for _, path := range paths {
		for k, a := range answers[path] {
			if err := gh.SeedAt(now.Add(time.Duration(k)*pause), map[string]string{path: a}); err != nil {
				t.Fatal(err)
			}
		}
	}
	return gh
}

// runsPath is where refresh asks for the pull_request runs of ci on head sha.
func runsPath(sha string) string {
	return "repos/o/r/actions/workflows/ci.yml/runs?head_sha=" + sha + "&event=pull_request&per_page=10"
}

// ciRunIn is GitHub's answer for the pull_request run id on a head, in status.
func ciRunIn(id int, status string) string {
	return fmt.Sprintf(`{"total_count":1,"workflow_runs":[{"id":%d,"event":"pull_request","status":%q}]}`, id, status)
}

const noRuns = `{"total_count":0,"workflow_runs":[]}`

// conflicted is GitHub refusing to merge main into PR #10's branch: they conflict.
type conflicted struct{ github.GitHub }

func (c conflicted) Send(method, path string, fields ...github.Field) ([]byte, error) {
	if path == "repos/o/r/pulls/10/update-branch" {
		return nil, &github.Error{Status: 422, Message: "gh: merge conflict between base and head"}
	}
	return c.GitHub.Send(method, path, fields...)
}

func TestRefreshUpdatesTheAutoMergePRsBehindMain(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := refreshGH(t, c, map[string][]string{
		openPullsPath: {"[" + strings.Join([]string{
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
		// The update's pull_request run shows a pause after the new head, waiting for approval.
		runsPath("a2"): {noRuns, noRuns, noRuns, ciRunIn(7, "action_required")},
	})
	got, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c}.Refresh()
	if err != nil {
		t.Fatal(err)
	}
	want := []Refreshed{
		{PR: 10, Branch: "issue-1", Head: "a2", Did: "merged main in at a2 and approved its ci.yml run 7"},
		{PR: 40, Branch: "issue-4", Head: "d1", Did: "left to its takeover: it conflicts with main"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v", got)
	}
	if want := []string{
		"PUT repos/o/r/pulls/10/update-branch",
		"POST repos/o/r/actions/runs/7/approve",
	}; !reflect.DeepEqual(gh.Writes(), want) {
		t.Fatalf("writes %q", gh.Writes())
	}
	if waited := c.Now().Sub(now); waited != 3*pause {
		t.Fatalf("waited %s", waited)
	}
}

func TestRefreshReportsAFailedUpdateAndGoesOn(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := refreshGH(t, c, map[string][]string{
		openPullsPath:                            {"[" + refreshPull(10, "a1", "", true) + "," + refreshPull(20, "b1", "", true) + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/compare/main...b1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/pulls/10":                     {refreshPull(10, "a1", "behind", true)},
		"repos/o/r/pulls/20":                     {refreshPull(20, "b1", "behind", true), refreshPull(20, "b2", "blocked", true)},
		runsPath("b2"):                           {ciRunIn(8, "action_required")},
	})
	got, err := Source{Proc: machine, Repo: repo, GitHub: conflicted{gh}, Clock: c}.Refresh()
	if err == nil || !strings.Contains(err.Error(), "could not bring PR #10 up to date with main") {
		t.Fatalf("%v", err)
	}
	if len(got) != 2 || !strings.Contains(got[0].Did, "failed: gh: merge conflict") || got[1].Head != "b2" {
		t.Fatalf("got %+v", got)
	}
	if len(gh.Writes()) != 2 {
		t.Fatalf("writes %q", gh.Writes())
	}
}

func TestRefreshSaysWhenTheHeadNeverMoves(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := refreshGH(t, c, map[string][]string{
		openPullsPath:                            {"[" + refreshPull(10, "a1", "", true) + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/pulls/10":                     {refreshPull(10, "a1", "behind", true)},
	})
	got, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c}.Refresh()
	if err == nil || len(got) != 1 || !strings.Contains(got[0].Failed, "head is still a1") {
		t.Fatalf("%+v %v", got, err)
	}
	// No run was approved on the old head.
	if len(gh.Writes()) != 1 {
		t.Fatalf("writes %q", gh.Writes())
	}
}

func TestRefreshApprovesNothingARunThatDoesNotWait(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := refreshGH(t, c, map[string][]string{
		openPullsPath:                            {"[" + refreshPull(10, "a1", "", true) + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/pulls/10":                     {refreshPull(10, "a1", "behind", true), refreshPull(10, "a2", "blocked", true)},
		runsPath("a2"):                           {ciRunIn(9, "queued")},
	})
	got, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c}.Refresh()
	if err != nil || len(got) != 1 || !strings.Contains(got[0].Did, "run 9 needs no approval (queued)") {
		t.Fatalf("%+v %v", got, err)
	}
	if want := []string{"PUT repos/o/r/pulls/10/update-branch"}; !reflect.DeepEqual(gh.Writes(), want) {
		t.Fatalf("writes %q", gh.Writes())
	}
}

func TestRefreshSaysWhenNoRunShows(t *testing.T) {
	t.Parallel()
	c := atNow()
	gh := refreshGH(t, c, map[string][]string{
		openPullsPath:                            {"[" + refreshPull(10, "a1", "", true) + "]"},
		"repos/o/r/compare/main...a1?per_page=1": {`{"behind_by":1}`},
		"repos/o/r/pulls/10":                     {refreshPull(10, "a1", "behind", true), refreshPull(10, "a2", "blocked", true)},
		runsPath("a2"):                           {noRuns},
	})
	got, err := Source{Proc: machine, Repo: repo, GitHub: gh, Clock: c}.Refresh()
	if err == nil || len(got) != 1 || !strings.Contains(got[0].Failed, "no pull_request run of ci.yml") {
		t.Fatalf("%+v %v", got, err)
	}
}
