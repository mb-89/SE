package git_test

import (
	"fmt"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/index/indextest"
	"github.com/mb-89/SE/src/modules/io/git"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// withOrigin is a git whose one checkout, dir, has origin at url; an empty url
// is no origin at all.
func withOrigin(dir, url string) proc.Program {
	return func(c proc.Cmd) int {
		switch {
		case c.Dir != dir:
			fmt.Fprintf(c.Stderr, "fatal: not a git repository: %s\n", c.Dir)
			return 128
		case strings.Join(c.Args, " ") != "remote get-url origin":
			fmt.Fprintf(c.Stderr, "git: %s is not what this git does\n", c.Args)
			return 1
		case url == "":
			fmt.Fprintln(c.Stderr, "error: No such remote 'origin'")
			return 2
		}
		fmt.Fprintln(c.Stdout, url)
		return 0
	}
}

// The verb origin reads OWNER/NAME from a checkout's origin URL, whatever its
// form, the workspace's where the folder asked is empty.
func TestOriginReadsTheRepositoryOfACheckout(t *testing.T) {
	t.Parallel()
	for url, want := range map[string]string{
		"https://github.com/mb-89/SE":              "mb-89/SE",
		"https://github.com/mb-89/SE.git":          "mb-89/SE",
		"git@github.com:mb-89/SE.git":              "mb-89/SE",
		"http://proxy@127.0.0.1:1234/git/mb-89/SE": "mb-89/SE",
	} {
		f, err := indextest.New(git.Module(git.NewFake(withOrigin("/ws", url)), "/ws"))
		if err != nil {
			t.Fatal(err)
		}
		for _, dir := range []string{"", "/ws"} {
			if got, err := f.Serve("origin", dir); err != nil || got != want {
				t.Errorf("%s in %q: %v %v", url, dir, got, err)
			}
		}
	}
	f, err := indextest.New(git.Module(git.NewFake(withOrigin("/ws", "")), "/ws"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.Serve("origin", ""); err == nil || !strings.Contains(err.Error(), "remote get-url origin") {
		t.Fatalf("a checkout without origin answered %v", err)
	}
	if _, err := f.Serve("origin", "/elsewhere"); err == nil || !strings.Contains(err.Error(), "not a git repository") {
		t.Fatalf("a folder that is no checkout answered %v", err)
	}
}
