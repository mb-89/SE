package daemon_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/index/fixture"
	"github.com/mb-89/SE/src/internal/daemon"
	"github.com/mb-89/SE/src/modules/io/clock"
	sehttp "github.com/mb-89/SE/src/modules/io/http"
)

// The daemon runs a command a module declared, as se posts it: the index
// delivers the command's requests to the verb the wiring binds, and the
// reply comes back as text, or as JSON where the call said --json.
func TestTheDaemonRunsAModulesCommandAndItsRequests(t *testing.T) {
	t.Parallel()
	w, err := index.ParseWiring([]byte(fixture.ShopWiring))
	if err != nil {
		t.Fatal(err)
	}
	ix, err := index.Start(w, fixture.Shelf(map[string]int{"apple": 2}), fixture.Shopper)
	if err != nil {
		t.Fatal(err)
	}
	n, clk := sehttp.NewFake(), clock.NewFake(time.Time{})
	ctx, cancel := context.WithCancel(context.Background())
	addr, done, err := n.Serve(ctx, "tok", daemon.NewServer(ix, "i1", nil, clk))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { cancel(); <-done })
	if r, err := n.Command(addr, "tok", sehttp.CommandCall{Name: "shop take", Words: []string{"apple"}}); err != nil || r.Text != "took a apple, 1 left" {
		t.Fatalf("shop take apple = %+v, %v", r, err)
	}
	if r, err := n.Command(addr, "tok", sehttp.CommandCall{Name: "shop take", Words: []string{"apple", "--json"}}); err != nil || r.Text != `{"thing":"apple","left":0}` {
		t.Fatalf("shop take apple --json = %+v, %v", r, err)
	}
	if _, err := n.Command(addr, "tok", sehttp.CommandCall{Name: "shop take", Words: []string{"apple"}}); err == nil || !strings.Contains(err.Error(), "no apple left") {
		t.Fatalf("a take off an empty shelf: %v", err)
	}
	if _, err := n.Command(addr, "tok", sehttp.CommandCall{Name: "shop take", Words: []string{"--nope"}}); err == nil {
		t.Fatal("a flag the command does not take was taken")
	}
	var refused *sehttp.StatusError
	if _, err := n.Command(addr, "tok", sehttp.CommandCall{Name: "shop sell"}); !errors.As(err, &refused) || refused.Status != sehttp.StatusNotFound {
		t.Fatalf("a command nothing declares: %v", err)
	}
}
