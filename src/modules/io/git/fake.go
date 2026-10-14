package git

import (
	"github.com/mb-89/SE/src/modules/io/env"
	"github.com/mb-89/SE/src/modules/io/proc"
)

// Fake is git on a fake machine, Machine, that holds git alone: run does
// what the real git would in the case's repositories, and Machine records
// every run, as proc's fake does. Its runs inherit an empty environment.
type Fake struct {
	Git
	// Machine is the fake machine git runs on: its Ran and Lines say what
	// ran, and its Delay makes each run take time.
	Machine *proc.Fake
}

// NewFake answers git that does what run does.
func NewFake(run proc.Program) *Fake {
	m := proc.NewFake()
	m.Install("git", run)
	return &Fake{Git: Real(m, env.NewFake()), Machine: m}
}
