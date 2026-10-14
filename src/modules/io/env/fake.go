package env

import (
	"fmt"
	"slices"
	"strings"
	"sync"
)

// Fake is an environment in memory, which fails as the real one does: a
// name that is empty or holds "=" or NUL cannot be set.
type Fake struct {
	mu   sync.Mutex
	vars map[string]string
}

// NewFake answers an environment holding vars, each key=value.
func NewFake(vars ...string) *Fake {
	f := &Fake{vars: map[string]string{}}
	for _, kv := range vars {
		k, v, _ := strings.Cut(kv, "=")
		f.vars[k] = v
	}
	return f
}

// Getenv answers the variable's value; "" where it is not set.
func (f *Fake) Getenv(key string) string {
	v, _ := f.LookupEnv(key)
	return v
}

// LookupEnv answers the variable's value and whether it is set.
func (f *Fake) LookupEnv(key string) (string, bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	v, ok := f.vars[key]
	return v, ok
}

// Environ answers every variable as key=value, sorted.
func (f *Fake) Environ() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([]string, 0, len(f.vars))
	for k, v := range f.vars {
		out = append(out, k+"="+v)
	}
	slices.Sort(out)
	return out
}

// Setenv sets the variable.
func (f *Fake) Setenv(key, value string) error {
	if err := name(key); err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.vars[key] = value
	return nil
}

// Unsetenv removes the variable.
func (f *Fake) Unsetenv(key string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.vars, key)
	return nil
}

// name refuses what no environment can name, as setenv does.
func name(key string) error {
	if key == "" || strings.ContainsAny(key, "=\x00") {
		return fmt.Errorf("setenv %q: invalid argument", key)
	}
	return nil
}
