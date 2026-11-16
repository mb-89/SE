package home_test

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"kern/git"
	"kern/git/gitfake"
	"kern/home"
)

// table is testdata/origins.json, which SE's Python helper's tests read too.
type table struct {
	Origins []struct {
		Origin string     `json:"origin"`
		Home   *home.Home `json:"home"`
	} `json:"origins"`
	Answers []struct {
		Home    home.Home         `json:"home"`
		URL     string            `json:"url"`
		Tracker string            `json:"tracker"`
		Docs    string            `json:"docs"`
		At      map[string]string `json:"at"`
		Named   map[string]string `json:"named"`
	} `json:"answers"`
}

func load(t *testing.T) table {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "origins.json"))
	if err != nil {
		t.Fatal(err)
	}
	var tb table
	if err := json.Unmarshal(data, &tb); err != nil {
		t.Fatal(err)
	}
	if len(tb.Origins) == 0 || len(tb.Answers) == 0 {
		t.Fatal("testdata/origins.json holds no cases")
	}
	return tb
}

// Each origin of the shared table names the home it lists, or none.
func TestEveryOriginOfTheTableNamesItsHome(t *testing.T) {
	for _, c := range load(t).Origins {
		got, ok := home.Parse(c.Origin)
		switch {
		case c.Home == nil && ok:
			t.Errorf("Parse(%q) answers %+v; the table names no home", c.Origin, got)
		case c.Home != nil && (!ok || got != *c.Home):
			t.Errorf("Parse(%q) answers %+v, %v; the table names %+v", c.Origin, got, ok, *c.Home)
		}
	}
}

// Each home of the shared table gives the answers it lists.
func TestEveryHomeOfTheTableGivesItsAnswers(t *testing.T) {
	for _, c := range load(t).Answers {
		h := c.Home
		if h.URL() != c.URL || h.Tracker() != c.Tracker || h.Docs() != c.Docs {
			t.Errorf("%+v answers %q, %q, %q; the table %q, %q, %q", h, h.URL(), h.Tracker(), h.Docs(), c.URL, c.Tracker, c.Docs)
		}
		for path, want := range c.At {
			if got := h.At(path); got != want {
				t.Errorf("%+v At(%q) = %q, want %q", h, path, got, want)
			}
		}
		for entry, want := range c.Named {
			if got := h.Named(entry); got != want {
				t.Errorf("%+v Named(%q) = %q, want %q", h, entry, got, want)
			}
		}
	}
}

// A checkout's home comes from its origin; without one, or with one of no
// form Parse reads, nothing guesses a home.
func TestTheCheckoutsHomeComesFromOrigin(t *testing.T) {
	defer git.Use(gitfake.New())()
	ctx := context.Background()
	root := t.TempDir()
	if _, err := git.Run(ctx, root, "init", "-q", "-b", "main"); err != nil {
		t.Fatal(err)
	}
	var none *home.NoHome
	if _, err := home.Of(ctx, root); !errors.As(err, &none) {
		t.Fatalf("a checkout without origin answers %v", err)
	}
	if _, err := git.Run(ctx, root, "config", "remote.origin.url", "http://proxy@127.0.0.1:1/git/alice/project"); err != nil {
		t.Fatal(err)
	}
	if _, err := home.Of(ctx, root); !errors.As(err, &none) {
		t.Fatalf("a proxy origin answers %v", err)
	}
	if _, err := git.Run(ctx, root, "config", "remote.origin.url", "git@example.com:alice/project.git"); err != nil {
		t.Fatal(err)
	}
	got, err := home.Of(ctx, root)
	if err != nil || got != (home.Home{Host: "example.com", Owner: "alice", Repository: "project"}) {
		t.Fatalf("Of answers %+v, %v", got, err)
	}
}
