// Internal test package: package main cannot be imported.
package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
	"github.com/mb-89/SE/src/internal/issues"
	"github.com/mb-89/SE/src/internal/reuse"
)

// ranAll is a report's ran naming every entry of the reviewer's list, as JSON.
func ranAll(t *testing.T) string {
	t.Helper()
	cfg, err := reuse.Configured()
	if err != nil {
		t.Fatal(err)
	}
	var ran []issues.Ran
	for _, s := range cfg.Tier[reuse.Reviewer] {
		ran = append(ran, issues.Ran{Skill: s, Found: "nothing"})
	}
	data, err := json.Marshal(ran)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// loaded puts the plugins of the reuse config into a folder of plugins on
// the fake d, as se fleet plugins lays them out, and points the session's
// plugin folders at it beside the se plugin.
func loaded(t *testing.T, d disk.Disk) string {
	t.Helper()
	dir := "/opt/se-plugins"
	put(t, d, filepath.Join(dir, "code-simplifier/.claude-plugin/plugin.json"), "{}")
	put(t, d, filepath.Join(dir, "code-simplifier/agents/code-simplifier.md"), "simplify")
	put(t, d, filepath.Join(dir, "skill-creator/.claude-plugin/plugin.json"), "{}")
	put(t, d, filepath.Join(dir, "skill-creator/skills/skill-creator/SKILL.md"), "create")
	put(t, d, filepath.Join(dir, reuse.Adopted, ".claude-plugin/plugin.json"), "{}")
	put(t, d, filepath.Join(dir, reuse.Adopted, "skills/clean-code/SKILL.md"), "clean")
	setenv(t, reuse.DirsVar, "/opt/se/src/plugin"+string(filepath.ListSeparator)+dir)
	return dir
}

func TestEachKindOfTakeIsHandedWhatItsTierRunsAsThisBoxLoadedIt(t *testing.T) {
	t.Parallel()
	d := onFake(t)
	dir := loaded(t, d)
	c := &Call{Workspace: "/ws", World: *worldOf(t)}
	leaf := c.handOver(issues.Issue{Number: 3, Body: "do it"})
	for _, want := range []string{
		workerIntro, "- simplify: a built-in skill; run it with the Skill tool (/simplify).",
		authorIntro, "- skill-creator:skill-creator: a skill from anthropics/claude-plugins-official@8bd00f08f0b0; run it with the Skill tool.",
		"- plugin-dev:agent-development: not on this box, since no folder of CLAUDE_CODE_PLUGIN_DIRS holds its plugin",
	} {
		if !strings.Contains(leaf.Text, want) {
			t.Errorf("a leaf's take lacks %q:\n%s", want, leaf.Text)
		}
	}
	if strings.Contains(leaf.Text, "clean-code") || len(leaf.Skills) != 0 {
		t.Errorf("a leaf got the overhaul's list, or skills its issue does not name: %+v", leaf)
	}
	overhaul := c.handOver(issues.Issue{Number: 4, Body: "judge it", Overhaul: true})
	for _, want := range []string{
		overhaulIntro, "- adopted:clean-code: a skill from cskwork/clean-code-skill@8476ba6f4f61; run it with the Skill tool.",
		"- code-simplifier:code-simplifier: an agent from anthropics/claude-plugins-official@8bd00f08f0b0; start it with the Agent tool, or, where you cannot start one, read " + filepath.Join(dir, "code-simplifier/agents/code-simplifier.md"),
		"searches these places", "- https://github.com/hesreallyhim/awesome-claude-code",
	} {
		if !strings.Contains(overhaul.Text, want) {
			t.Errorf("an overhaul's take lacks %q:\n%s", want, overhaul.Text)
		}
	}
	if strings.Contains(overhaul.Text, workerIntro) {
		t.Errorf("an overhaul got the worker's list:\n%s", overhaul.Text)
	}
	for _, i := range []issues.Issue{{Number: 5, Parent: true}, {Number: 6, Retro: true}} {
		if h := c.handOver(i); h.Text != "" {
			t.Errorf("#%d was handed %q", i.Number, h.Text)
		}
	}
	// The reviewer's list follows the brief, on the same resolution.
	if text := c.reused(reuse.Reviewer, reviewerIntro); !strings.Contains(text, "## What you run on the delta") || !strings.Contains(text, "- security-review: a built-in skill") || !strings.Contains(text, "- pr-review-toolkit:code-reviewer: not on this box") {
		t.Errorf("the reviewer's list: %s", text)
	}
}

func TestAReviewReportNamesEachThingTheReviewerRanOnTheDelta(t *testing.T) {
	t.Parallel()
	gh := recordedIssues(t)
	d, dir := onFake(t), filepath.FromSlash("/reports")
	cases := map[string]string{
		`[{"skill":"security-review","found":"nothing"}]`:                                   "the report's ran does not name code-simplifier:code-simplifier, pr-review-toolkit:code-reviewer",
		`[{"skill":"security-review","found":" "}]`:                                         "names security-review without what it found",
		`[{"skill":"security-review","found":"a"},{"skill":"security-review","found":"b"}]`: "names security-review twice",
	}
	for ran, want := range cases {
		path := filepath.Join(dir, "r.json")
		put(t, d, path, `{"commit":"c","requirements":[{"item":"i","evidence":"e"}],"clean":["x"],"ran":`+ran+`}`)
		if code, _, errs := se(t, "issue", "review", "pass", "3", "--report", path, "--repo", "o/r"); code != 1 || !strings.Contains(errs, want) {
			t.Errorf("%s: exit %d, %q, want %q", ran, code, errs, want)
		}
	}
	if w := gh.Writes(); len(w) != 0 {
		t.Fatalf("a refused review wrote %q", w)
	}
}

func TestFleetPluginsFetchesEverySourceAtItsPinAsAFolderOfPlugins(t *testing.T) {
	t.Parallel()
	if code, _, errs := se(t, "fleet", "plugins"); code != 1 || !strings.Contains(errs, "needs --into") {
		t.Fatalf("exit %d, %q", code, errs)
	}
	d := onFake(t)
	m := proc.NewFake()
	onMachine(t, m)
	// git makes the repository it is asked for, and checks a tree out as one file.
	m.Install("git", func(c proc.Cmd) int {
		switch {
		case c.Args[2] == "init":
			if err := d.MkdirAll(filepath.Join(c.Args[1], ".git")); err != nil {
				return 1
			}
		case strings.HasPrefix(c.Args[2], "--work-tree="):
			if err := d.WriteFile(filepath.Join(strings.TrimPrefix(c.Args[2], "--work-tree="), "SKILL.md"), []byte("x")); err != nil {
				return 1
			}
		}
		return 0
	})
	into := filepath.FromSlash("/opt/se-plugins")
	put(t, d, filepath.Join(into, "gone/.claude-plugin/plugin.json"), "{}")
	put(t, d, filepath.Join(into, reuse.Adopted, "skills/gone/SKILL.md"), "x")
	code, out, errs := se(t, "fleet", "plugins", "--into", into)
	if code != 0 {
		t.Fatalf("exit %d, %q %q", code, out, errs)
	}
	cfg, err := reuse.Configured()
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range cfg.Sources {
		if !strings.Contains(out, s.Name+": "+s.Repo+" "+s.Path+" at "+s.Commit[:12]+" ("+s.Licence+")") {
			t.Errorf("no line for %s: %s", s.Name, out)
		}
	}
	lines := strings.Join(m.Lines(), "\n")
	for _, want := range []string{
		"git -C " + filepath.Join(into, reuse.Repos, "anthropics-claude-plugins-official") + " fetch -q --depth 1 https://github.com/anthropics/claude-plugins-official 8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3",
		"--work-tree=" + filepath.Join(into, "pr-review-toolkit") + " checkout -q 8bd00f08f0b04705e610cf132fbe2cf5ec44cfe3:plugins/pr-review-toolkit -- .",
		"--work-tree=" + filepath.Join(into, reuse.Adopted, "skills", "clean-code") + " checkout -q 8476ba6f4f6146095d653d9ee09c53fe970f599e -- .",
	} {
		if !strings.Contains(lines+"\n", want) {
			t.Errorf("no run %q in:\n%s", want, lines)
		}
	}
	if n := strings.Count(lines, " init -q"); n != 2 {
		t.Errorf("%d repositories were made, want one per repository:\n%s", n, lines)
	}
	if data, err := d.ReadFile(filepath.Join(into, reuse.Adopted, ".claude-plugin/plugin.json")); err != nil || !strings.Contains(string(data), `"name": "adopted"`) {
		t.Errorf("the adopted plugin's manifest: %q %v", data, err)
	}
	for _, gone := range []string{"gone", filepath.Join(reuse.Adopted, "skills", "gone")} {
		if ok, _ := d.Exists(filepath.Join(into, gone)); ok {
			t.Errorf("%s, which no source names, stayed", gone)
		}
	}
	if !strings.Contains(out, "gone: removed") || !strings.Contains(out, reuse.DirsVar+"=<the se plugin>"+string(filepath.ListSeparator)+into) {
		t.Errorf("%s", out)
	}
}
