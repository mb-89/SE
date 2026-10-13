package main

import (
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/update"
)

const (
	aaa = "aaaaaaa1111111111111111111111111111111111"
	bbb = "bbbbbbb2222222222222222222222222222222222"
)

// What /se status says about the commits, recorded for each case.
func TestCommitsAgainstRecordedAnswers(t *testing.T) {
	for _, c := range []struct{ name, hooks, checkout, built, want string }{
		{"all agree", aaa, aaa, aaa, `Hooks loaded from:   aaaaaaa
Plugin checkout at:  aaaaaaa
se built from:       aaaaaaa
They agree.`},
		{"the checkout moved under loaded hooks", aaa, bbb, bbb, `Hooks loaded from:   aaaaaaa
Plugin checkout at:  bbbbbbb
se built from:       bbbbbbb
They disagree: the hooks are not the checkout's: they load again on /reload-plugins or in a new session.`},
		{"se is another build", aaa, aaa, bbb, `Hooks loaded from:   aaaaaaa
Plugin checkout at:  aaaaaaa
se built from:       bbbbbbb
They disagree: se was not built from the checkout.`},
		{"both differ", bbb, aaa, bbb, `Hooks loaded from:   bbbbbbb
Plugin checkout at:  aaaaaaa
se built from:       bbbbbbb
They disagree: the hooks are not the checkout's: they load again on /reload-plugins or in a new session; se was not built from the checkout.`},
		{"nothing known", "", "", "", `Hooks loaded from:   unknown
Plugin checkout at:  unknown
se built from:       unknown
Whether they agree is unknown: the hooks', the checkout's, se's commit is not known.`},
		{"hooks unknown, as on a terminal", "", aaa, aaa, `Hooks loaded from:   unknown
Plugin checkout at:  aaaaaaa
se built from:       aaaaaaa
Whether they agree is unknown: the hooks' commit is not known.`},
	} {
		if got := commits(c.hooks, c.checkout, c.built); got != c.want {
			t.Errorf("%s:\n%s\nwant\n%s", c.name, got, c.want)
		}
	}
}

func TestStatusSaysTheCommitsThePluginNames(t *testing.T) {
	repo := checkout(t, "main")
	head, err := update.Head(repo)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv(hooksCommitEnv, aaa)
	t.Setenv(pluginRepoEnv, repo)
	saved := commit
	commit = head
	defer func() { commit = saved }()
	r := session(t, "status")
	lines := strings.Split(r.Text, "\n")
	if len(lines) != 5 || !strings.HasPrefix(lines[0], "No SE daemon answers") {
		t.Fatalf("%q", r.Text)
	}
	if want := commits(aaa, head, head); strings.Join(lines[1:], "\n") != want {
		t.Fatalf("%q, want %q", r.Text, want)
	}
}
