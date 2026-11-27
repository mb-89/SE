package start_test

import (
	"context"
	"errors"
	"path/filepath"
	"reflect"
	"testing"

	"se/components/start"
)

// finder is a Run that answers as SE's Python finder would, recording each call; it starts no
// process.
type finder struct {
	out, errs string
	code      int
	err       error
	calls     [][]string
	dirs      []string
}

func (f *finder) run(_ context.Context, dir string, argv []string) (string, string, int, error) {
	f.calls = append(f.calls, argv)
	f.dirs = append(f.dirs, dir)
	return f.out, f.errs, f.code, f.err
}

func project(t *testing.T) string {
	t.Helper()
	root := filepath.Join(t.TempDir(), "project")
	write(t, filepath.Join(root, "se.toml"), "[components.obs]\nversion = \"^4.0\"\n")
	return root
}

func TestComponentsRunsSEsFinderOnTheProjectAndShowsWhatItSays(t *testing.T) {
	root := project(t)
	f := &finder{out: "optional component se -> style not found on any remote's owner\n"}

	said, stopped := start.Components(ctx, "/se", root, f.run)

	if stopped || !reflect.DeepEqual(said, []string{"optional component se -> style not found on any remote's owner"}) {
		t.Fatalf("got %q, stopped %v", said, stopped)
	}
	want := []string{"uv", "run", "--no-project", "--python", ">=3.11", "python", "/se/scripts/se_modules.py",
		"--root", root, "sync", "--quiet"}
	if !reflect.DeepEqual(f.calls, [][]string{want}) || f.dirs[0] != root {
		t.Fatalf("ran %q in %q", f.calls, f.dirs)
	}
}

func TestAPlacedTreeSaysNothingAndTheStartGoesOn(t *testing.T) {
	said, stopped := start.Components(ctx, "/se", project(t), (&finder{}).run)
	if said != nil || stopped {
		t.Fatalf("got %q, stopped %v", said, stopped)
	}
}

func TestARequiredComponentMissingStopsTheStartWithTheFindersMessage(t *testing.T) {
	f := &finder{code: 1, errs: "se_modules: github.com answered HTTP 403 listing team's components; trying again in 10 s\n" +
		"error: the required component obs is missing (se -> obs).\n" +
		"No remote's owner offers a repository obs marked as a component (read: origin).\n" +
		"Add a remote of an owner that offers it: git remote add <remote> <address>\n"}

	said, stopped := start.Components(ctx, "/se", project(t), f.run)

	want := []string{"SE cannot start: the required component obs is missing (se -> obs).",
		"No remote's owner offers a repository obs marked as a component (read: origin).",
		"Add a remote of an owner that offers it: git remote add <remote> <address>"}
	if !stopped || !reflect.DeepEqual(said, want) {
		t.Fatalf("got %q, stopped %v", said, stopped)
	}
}

func TestAnyOtherFailureOfTheFinderStopsTheStartNamingIt(t *testing.T) {
	cases := map[string]struct {
		f    finder
		want string
	}{
		"a crash":        {finder{code: 1, errs: "Traceback (most recent call last):\n  ...\nValueError: boom\n"}, "ValueError: boom"},
		"no word":        {finder{code: 2}, "it exited 2 without a word"},
		"no uv to start": {finder{err: errors.New(`exec: "uv": executable file not found in $PATH`)}, `exec: "uv": executable file not found in $PATH`},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			said, stopped := start.Components(ctx, "/se", project(t), c.f.run)
			want := []string{"SE cannot start: resolving the components failed: " + c.want}
			if !stopped || !reflect.DeepEqual(said, want) {
				t.Fatalf("got %q, stopped %v", said, stopped)
			}
		})
	}
}

func TestAProjectWithoutAnSETomlSaysNothingAndRunsNoFinder(t *testing.T) {
	f := &finder{code: 1, errs: "error: never asked\n"}
	for _, root := range []string{"", t.TempDir()} {
		if said, stopped := start.Components(ctx, "/se", root, f.run); said != nil || stopped {
			t.Fatalf("%q: got %q, stopped %v", root, said, stopped)
		}
	}
	if len(f.calls) != 0 {
		t.Fatalf("ran %q", f.calls)
	}
}
