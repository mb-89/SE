package main

import (
	"testing"

	"kern/components/clock"
	"kern/components/github"
	"kern/components/session"
	"kern/index"
)

// SE's wiring reaches the environment only through the components kern's
// packages register, each built from its package's Environment() (kern 3:
// an I/O module's zero Options reach nothing). So the se binary carries
// exactly those for kern's clock, GitHub and session, and builds none of its
// own: one built from zero Options would read no token, no proxy and no
// cloud session, and stop SE's start reading GitHub.
func TestTheBinaryCarriesKernsComponentsBuiltFromTheEnvironment(t *testing.T) {
	want := map[string]*index.Component{
		clock.Name:   clock.Component.Component,
		github.Name:  github.Component.Component,
		session.Name: session.Component.Component,
	}
	seen := map[string]int{}
	for _, c := range index.Registered() {
		w, kern := want[c.Name()]
		if !kern {
			continue
		}
		seen[c.Name()]++
		if c != w {
			t.Errorf("the se binary carries a %s component of its own, and wants kern's, built from %s.Environment()", c.Name(), c.Name())
		}
	}
	for name := range want {
		if seen[name] != 1 {
			t.Errorf("the se binary carries %d %s components, and wants kern's one", seen[name], name)
		}
	}
}
