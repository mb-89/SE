// Internal test package: it uses the fakes of the package's other internal tests.
package issues

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// manifestsPath is the open manifests, as se fleet refresh lists them.
const manifestsPath = "repos/o/r/issues?labels=" + ManifestLabel + "&state=open&per_page=100"

// behindManifests is box a's clone of an origin whose main moved past the
// branches of manifests #5 (cleanly) and #6 (in conflict), and of #7, whose
// PR into main is open; #8's branch is main, and #9 has no branch yet.
func behindManifests(t *testing.T) (origin, a string) {
	t.Helper()
	origin, a, _ = boxes(t)
	// The workflow names whoever merges, as a box is named already.
	run(t, a, "config", "user.name", "t")
	run(t, a, "config", "user.email", "t@t")
	branchWith(t, a, "issue-5", "five", "5")
	branchWith(t, a, "issue-6", "shared", "from #6")
	branchWith(t, a, "issue-7", "seven", "7")
	commitFile(t, a, "shared", "from main")
	run(t, a, "push", "-q", "origin", "main", "main:issue-8")
	return origin, a
}

// manifestsGH answers the manifests #5 to #9, their branches, and #7's open PR.
func manifestsGH(t *testing.T) *world {
	t.Helper()
	w := newWorld(t, []string{item(5, 1, ManifestLabel), item(6, 1, ManifestLabel), item(7, 1, ManifestLabel), item(8, 1, ManifestLabel), item(9, 1, ManifestLabel)}, 5, 6, 7, 8)
	w.set(manifestsPath, get(t, w, listPath))
	w.set(openPullsPath, "["+rulesPull(70, "issue-7")+"]")
	return w
}

func TestRefreshMergesMainIntoEachOpenManifestsBranch(t *testing.T) {
	t.Parallel()
	origin, a := behindManifests(t)
	before6 := run(t, origin, "rev-parse", "issue-6")
	w := manifestsGH(t)
	got, err := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Refresh(a)
	if err != nil {
		t.Fatal(err)
	}
	dids := map[int]string{}
	for _, r := range got {
		dids[r.Issue] = fmt.Sprintf("%v %v %s", r.Merged, r.Conflict, r.Did)
	}
	want := map[int]string{
		5: "true false merged main in and pushed",
		6: "false true conflicts with main, so nothing was pushed: merge origin/main into issue-6 by hand (never rebase), as se issue land of #6 does",
		8: "false false up to date with main",
	}
	if !reflect.DeepEqual(dids, want) {
		t.Fatalf("got %v", dids)
	}
	// Merged in, never rebased: issue-5 holds main through a merge.
	run(t, origin, "merge-base", "--is-ancestor", "main", "issue-5")
	if parents := strings.Fields(run(t, origin, "log", "-1", "--format=%P", "issue-5")); len(parents) != 2 {
		t.Fatalf("issue-5's refresh is no merge: %v", parents)
	}
	if got := run(t, origin, "rev-parse", "issue-6"); got != before6 {
		t.Fatalf("the conflicted issue-6 moved to %s", got)
	}
	if _, err := os.Stat(filepath.Join(a, filepath.FromSlash(RefreshDir), "issue-5")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("worktree left: %v", err)
	}
	if st := run(t, a, "status", "--porcelain"); st != "" {
		t.Fatalf("the clone changed: %s", st)
	}
	if wr := w.Writes(); len(wr) != 0 {
		t.Fatalf("it wrote to GitHub: %q", wr)
	}
}

func TestAManifestBehindMainIsAStaleManifestThatFleetFixRefreshes(t *testing.T) {
	t.Parallel()
	_, a := behindManifests(t)
	w := manifestsGH(t)
	for n, by := range map[int]int{5: 1, 6: 1, 7: 1, 8: 0} {
		w.set(fmt.Sprintf("repos/o/r/compare/c%d...main?per_page=1", n), fmt.Sprintf(`{"ahead_by":%d}`, by))
	}
	var stale []Finding
	for _, f := range w.check() {
		if f.Kind == StaleManifest {
			stale = append(stale, f)
		}
	}
	if len(stale) != 2 || stale[0].Issue != 5 || stale[1].Issue != 6 ||
		stale[0].What != "issue-5 lacks 1 commit(s) of main, which its leaves would each meet on their own" ||
		!strings.HasPrefix(stale[0].Remedy, "se fleet fix merges origin/main into issue-5") {
		t.Fatalf("%+v", stale)
	}
	done := Source{Proc: machine, Repo: repo, GitHub: w, Clock: atNow()}.Fix(a, stale)
	if done[0].Did != "merged main in and pushed" || done[0].Failed != "" || !strings.HasPrefix(done[1].Did, "conflicts with main") {
		t.Fatalf("%+v", done)
	}
	// Main moves often: a refresh is no fix to record.
	if wr := w.Writes(); len(wr) != 0 {
		t.Fatalf("it wrote to GitHub: %q", wr)
	}
}
