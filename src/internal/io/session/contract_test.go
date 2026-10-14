package session_test

import (
	"sync"
	"testing"

	"github.com/mb-89/SE/src/internal/io/session"
)

// contract is the one suite every Log keeps, the fake as the real folder.
// fresh answers a new, empty log folder for each case.
func contract(t *testing.T, fresh func(t *testing.T) session.Log) {
	t.Run("a session never appended reads empty", func(t *testing.T) {
		got, err := fresh(t).Read("s1")
		if err != nil || len(got) != 0 {
			t.Fatalf("read %q, %v", got, err)
		}
	})
	t.Run("lines land in order, each on a line, in their own session's log", func(t *testing.T) {
		l := fresh(t)
		for _, a := range []struct{ s, line string }{{"s1", "a"}, {"s2", "x"}, {"s1", "b"}} {
			if err := l.Append(a.s, []byte(a.line)); err != nil {
				t.Fatal(err)
			}
		}
		if got, err := l.Read("s1"); err != nil || string(got) != "a\nb\n" {
			t.Fatalf("s1 reads %q, %v", got, err)
		}
		if got, err := l.Read("s2"); err != nil || string(got) != "x\n" {
			t.Fatalf("s2 reads %q, %v", got, err)
		}
	})
	t.Run("a session name cannot leave the folder", func(t *testing.T) {
		l := fresh(t)
		for _, s := range []string{"../escape", "a/b", "", ".hidden"} {
			if err := l.Append(s, []byte("x")); err == nil {
				t.Fatalf("appended to session %q", s)
			}
		}
	})
	t.Run("lines appended at once all land", func(t *testing.T) {
		l := fresh(t)
		var wg sync.WaitGroup
		for range 20 {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_ = l.Append("s1", []byte("line"))
			}()
		}
		wg.Wait()
		if got, _ := l.Read("s1"); len(got) != 20*len("line\n") {
			t.Fatalf("read %d bytes", len(got))
		}
	})
}
