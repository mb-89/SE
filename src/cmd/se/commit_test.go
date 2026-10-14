// Internal test package: package main cannot be imported.
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
	t.Parallel()
	for _, c := range []struct{ name, hooks, checkout, built, want string }{
		{"all agree", aaa, aaa, aaa, `Hooks, checkout and se agree at aaaaaaa.`},
		{"the checkout moved under loaded hooks", aaa, bbb, bbb, `Hooks loaded from aaaaaaa.
Checkout at bbbbbbb.
se built from bbbbbbb.
They disagree: start a new session.`},
		{"se is another build", aaa, aaa, bbb, `Hooks loaded from aaaaaaa.
Checkout at aaaaaaa.
se built from bbbbbbb.
They disagree: start a new session.`},
		{"both differ", bbb, aaa, bbb, `Hooks loaded from bbbbbbb.
Checkout at aaaaaaa.
se built from bbbbbbb.
They disagree: start a new session.`},
		{"nothing known", "", "", "", `Hooks loaded from unknown.
Checkout at unknown.
se built from unknown.
Whether they agree is unknown.`},
		{"hooks unknown, as on a terminal", "", aaa, aaa, `Hooks loaded from unknown.
Checkout at aaaaaaa.
se built from aaaaaaa.
Whether they agree is unknown.`},
	} {
		if got := commits(c.hooks, c.checkout, c.built); got != c.want {
			t.Errorf("%s:\n%s\nwant\n%s", c.name, got, c.want)
		}
	}
}

func TestStatusSaysTheCommitsThePluginNames(t *testing.T) {
	t.Parallel()
	repo := checkout(t, "main")
	head, err := update.Head(worldOf(t).Proc, repo)
	if err != nil {
		t.Fatal(err)
	}
	setenv(t, hooksCommitEnv, aaa)
	setenv(t, pluginRepoEnv, repo)
	worldOf(t).Commit = head
	r := session(t, "status")
	lines := strings.Split(r.Text, "\n")
	if len(lines) != 5 || !strings.HasPrefix(lines[0], "No SE daemon answers") {
		t.Fatalf("%q", r.Text)
	}
	if want := commits(aaa, head, head); strings.Join(lines[1:], "\n") != want {
		t.Fatalf("%q, want %q", r.Text, want)
	}
	// Where they agree, status is one line.
	setenv(t, hooksCommitEnv, head)
	if r := session(t, "status"); strings.Contains(r.Text, "\n") || !strings.HasSuffix(r.Text, "Hooks, checkout and se agree at "+short(head)+".") {
		t.Fatalf("%q", r.Text)
	}
}
