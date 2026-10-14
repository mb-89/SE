// Package env is the I/O module for the environment: the one place SE reads
// or changes its process's environment variables. Code that needs one takes
// an Env as an argument; the se binary hands it Real, a test hands it a Fake,
// so a case never depends on the environment it happens to run in.
package env

import (
	"os"

	"github.com/mb-89/SE/src/index"
)

// Env is what SE asks of the environment.
type Env interface {
	// Getenv answers the variable's value; "" where it is not set.
	Getenv(key string) string
	// LookupEnv answers the variable's value and whether it is set.
	LookupEnv(key string) (string, bool)
	// Environ answers every variable as key=value.
	Environ() []string
	// Setenv sets the variable for this process and what it starts.
	Setenv(key, value string) error
	// Unsetenv removes the variable; one that is not set stays so.
	Unsetenv(key string) error
}

// Module is the environment on the index: an I/O module.
var Module = index.Declare("io/env", "The environment variables of SE's process.", index.IO())

func init() { index.Register(Module) }

// Real answers this process's environment.
func Real() Env { return process{} }

type process struct{}

func (process) Getenv(key string) string            { return os.Getenv(key) }
func (process) LookupEnv(key string) (string, bool) { return os.LookupEnv(key) }
func (process) Environ() []string                   { return os.Environ() }
func (process) Setenv(key, value string) error      { return os.Setenv(key, value) }
func (process) Unsetenv(key string) error           { return os.Unsetenv(key) }
