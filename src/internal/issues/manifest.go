package issues

import (
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/index"
	"github.com/mb-89/SE/src/internal/io/github"
)

// All work moves in manifests (the owner, 2026-10-14). A manifest is an
// issue at the top whose sub-issues are its work: its coordinator works it on
// one branch, issue-<manifest>, each leaf lands into that branch, and the
// manifest lands once, as one PR. Boxes take only manifests at the top.

// ManifestTarget is the built-in value of issues.manifest/config/target
// (issues/config/manifest-target on the index): how long one manifest's
// leaves together should take, and how long a misc manifest takes new issues
// from its creation.
const ManifestTarget = time.Hour

// ManifestLabel marks an issue as a manifest: it lands as one PR from its
// branch, so it never closes by itself once its leaves are done. A leaf's
// landing labels its manifest so.
const ManifestLabel = "se-manifest"

// MiscLabel marks a misc manifest: it takes the issues filed into no manifest
// for the target time from its creation.
const MiscLabel = "se-misc"

// atTop says whether an issue labelled so stands at the top by itself, in no
// manifest: a manifest, a retro, an overhaul, or an issue for a person.
func atTop(labels []string) bool {
	for _, l := range []string{ManifestLabel, RetroLabel, OverhaulLabel, PersonLabel} {
		if slices.Contains(labels, l) {
			return true
		}
	}
	return false
}

// manifestOf answers the top of issue n's tree, the manifest it lands into:
// its parent's parent and so on; 0 where n has no parent.
func (s Source) manifestOf(n int) (int, error) {
	top := 0
	for m, k := n, 0; k < 32; k++ {
		got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/parent", s.Repo, m), false)
		if err != nil {
			if github.Status(err) == 404 {
				return top, nil
			}
			return 0, err
		}
		top, m = got[0].Number, got[0].Number
	}
	return top, nil
}

// openPR answers the open PR from issue n's branch into main, where one is.
func (s Source) openPR(n int) (pull, bool, error) {
	owner, _, _ := strings.Cut(s.Repo, "/")
	open, err := api[pull](s, fmt.Sprintf("repos/%s/pulls?head=%s:%s&base=main&state=open&per_page=100", s.Repo, owner, Branch(n)), true)
	if err != nil || len(open) == 0 {
		return pull{}, false, err
	}
	return open[0], true, nil
}

// Misc names the open misc manifest that takes new issues now: the newest
// open issue labelled se-misc, created within the target time, whose PR is
// not open yet; 0 where none does.
func (s Source) Misc() (int, error) {
	list, err := api[issue](s, fmt.Sprintf("repos/%s/issues?labels=%s&state=open&per_page=100", s.Repo, MiscLabel), true)
	if err != nil {
		return 0, err
	}
	var best issue
	for _, i := range list {
		if i.PullRequest != nil || i.State != "open" || !s.now().Before(i.Created.Add(s.config().ManifestTarget)) {
			continue
		}
		if best.Number == 0 || i.Created.After(best.Created) {
			best = i
		}
	}
	if best.Number == 0 {
		return 0, nil
	}
	if _, open, err := s.openPR(best.Number); err != nil || open {
		return 0, err
	}
	return best.Number, nil
}

// FileInto names the manifest an issue filed into none goes into: the open
// misc manifest, or the next one, which it opens.
func (s Source) FileInto() (int, error) {
	if m, err := s.Misc(); err != nil || m > 0 {
		return m, err
	}
	target := s.config().ManifestTarget
	title := "Misc manifest " + s.now().UTC().Format("2006-01-02 15:04")
	body := fmt.Sprintf("The misc manifest: it takes the se issues filed into no manifest for %s from its creation (issues.manifest/config/target), then the next one opens. It lands once its leaves are done, as one PR.", Span(target.Minutes()))
	made, _, err := s.create(title, body, 0, nil, []string{Label, ManifestLabel, MiscLabel})
	if err != nil {
		return 0, fmt.Errorf("opening the next misc manifest: %w", err)
	}
	return made.Number, nil
}

// Paused reads fleet.box/config/paused (issues/config/paused on the index)
// from the wiring file on origin/main, fetched into the checkout dir: the
// owner stops the fleet with one change on main, and it reaches every running
// box before its next take. A main without the file, or one that cannot be
// fetched, is not paused.
func (s Source) Paused(dir string) (bool, error) {
	// Where main cannot be read, the take that follows says why.
	if _, err := s.git(dir, "fetch", "-q", "origin", "main"); err != nil {
		return false, nil
	}
	data, err := s.git(dir, "show", "origin/main:"+index.WiringFile)
	if err != nil {
		return false, nil
	}
	w, err := index.ParseWiring([]byte(data))
	if err != nil {
		return false, fmt.Errorf("the wiring file on origin/main: %w", err)
	}
	set, err := From(w)
	if err != nil {
		return false, fmt.Errorf("the wiring file on origin/main: %w", err)
	}
	return set.Paused, nil
}

// PausedWhy is what a take says when the fleet is paused.
const PausedWhy = "the fleet is paused (fleet.box/config/paused is set on main): take nothing, and end"

// labelManifest labels issue n se-manifest, where it is not yet.
func (s Source) labelManifest(n int) error {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return err
	}
	if got[0].labelled(ManifestLabel) {
		return nil
	}
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/labels", s.Repo, n), github.F("labels[]", ManifestLabel)); err != nil {
		return fmt.Errorf("labelling #%d %s: %w", n, ManifestLabel, err)
	}
	return nil
}

// landInto lands leaf n, checked out in dir, into its manifest's branch: it
// merges origin's copy of the leaf's branch and then the manifest's branch
// into it (never a rebase), runs check, and pushes the result to both
// branches at once, a fast-forward of the manifest's branch. Where another
// leaf landed in between, it merges the manifest's branch again and pushes
// again; the manifest's PR checks the whole. Then it records the worker,
// posts the landing answers on the leaf and closes it: a leaf gets no PR.
func (s Source) landInto(dir string, n, root int, session string, qs []Question, answers map[string]string, check func(dir string) error) (Landing, error) {
	branch, into := Branch(n), Branch(root)
	if err := s.takeInto(dir, branch, into); err != nil {
		return Landing{}, err
	}
	if err := check(dir); err != nil {
		return Landing{}, fmt.Errorf("the check failed, so nothing was pushed: %w", err)
	}
	comments, f, err := s.factsOf(dir, n, into)
	if err != nil {
		return Landing{}, err
	}
	// The answers go on the issue before the push, as Land's do.
	if err := s.record(n, Worker{Session: session, Workspace: dir}); err != nil {
		return Landing{}, err
	}
	if err := s.post(n, comments, qs, Landed{Issue: n, Answers: answers, Facts: f}); err != nil {
		return Landing{}, err
	}
	for k := 0; ; k++ {
		_, err := s.git(dir, "push", "-q", "--atomic", "origin", "HEAD:refs/heads/"+into, "HEAD:refs/heads/"+branch)
		if err == nil {
			break
		}
		if k == 4 {
			return Landing{}, fmt.Errorf("pushing #%d into %s: %w", n, into, err)
		}
		if err := s.mergeIn(dir, branch, into); err != nil {
			return Landing{}, err
		}
	}
	if err := s.labelManifest(root); err != nil {
		return Landing{}, err
	}
	path := fmt.Sprintf("repos/%s/issues/%d", s.Repo, n)
	note := fmt.Sprintf("Landed into %s, the branch of manifest #%d, which lands as one PR once its leaves are done.", into, root)
	if _, err := s.GitHub.Send("POST", path+"/comments", github.F("body", note)); err != nil {
		return Landing{}, fmt.Errorf("landed #%d into %s, but %w", n, into, err)
	}
	if _, err := s.GitHub.Send("PATCH", path, github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
		return Landing{}, fmt.Errorf("landed #%d into %s, but closing it: %w", n, into, err)
	}
	return Landing{Issue: n, Manifest: root, Into: into, Closed: true}, nil
}

// takeInto merges into the leaf's branch checked out in dir what origin's
// copy of it has, then the manifest's branch into, which must be on origin:
// its coordinator claimed it.
func (s Source) takeInto(dir, branch, into string) error {
	if _, err := s.git(dir, "fetch", "-q", "origin", "refs/heads/"+branch+":refs/remotes/origin/"+branch); err == nil {
		if _, err := s.git(dir, "merge", "-q", "--no-edit", "origin/"+branch); err != nil {
			_, _ = s.git(dir, "merge", "--abort")
			return fmt.Errorf("merging origin/%s into %s conflicts, so nothing was pushed: merge it by hand (never rebase), resolve the conflict, commit and land again: %w", branch, branch, err)
		}
	}
	return s.mergeIn(dir, branch, into)
}

// mergeIn fetches the manifest's branch into and merges it into the branch
// checked out in dir; a merge that conflicts is undone.
func (s Source) mergeIn(dir, branch, into string) error {
	if _, err := s.git(dir, "fetch", "-q", "origin", "+refs/heads/"+into+":refs/remotes/origin/"+into); err != nil {
		return fmt.Errorf("the manifest's branch %s is not on origin, so nothing was pushed (its coordinator claims it): %w", into, err)
	}
	if _, err := s.git(dir, "merge", "-q", "--no-edit", "origin/"+into); err != nil {
		_, _ = s.git(dir, "merge", "--abort")
		return fmt.Errorf("merging origin/%s into %s conflicts, so nothing was pushed: merge it by hand (never rebase), resolve the conflict, commit and land again: %w", into, branch, err)
	}
	return nil
}

// openTo names the open PR into main from branch among pulls, where one is.
func openTo(pulls []openPull, branch string) (int, bool) {
	p, ok := toMain(pulls)[branch]
	return p.Number, ok
}
