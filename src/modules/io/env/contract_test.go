package env_test

import (
	"slices"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/modules/io/env"
)

// contract is the one suite every Env keeps, the fake as the real one. fresh
// answers an environment for each case; key is a variable name no other case
// or test uses, so the real environment's cases do not meet.
func contract(t *testing.T, fresh func() env.Env) {
	key := func(t *testing.T) string {
		return "SE_ENV_CONTRACT_" + strings.NewReplacer("/", "_", " ", "_").Replace(t.Name())
	}
	t.Run("a variable set is read back", func(t *testing.T) {
		e, k := fresh(), key(t)
		if err := e.Setenv(k, "a=b"); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = e.Unsetenv(k) })
		if got := e.Getenv(k); got != "a=b" {
			t.Fatalf("got %q", got)
		}
		if v, ok := e.LookupEnv(k); !ok || v != "a=b" {
			t.Fatalf("lookup %q, %v", v, ok)
		}
		if !slices.Contains(e.Environ(), k+"=a=b") {
			t.Fatalf("environ lacks %s", k)
		}
	})
	t.Run("an empty variable is set", func(t *testing.T) {
		e, k := fresh(), key(t)
		if err := e.Setenv(k, ""); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = e.Unsetenv(k) })
		if v, ok := e.LookupEnv(k); !ok || v != "" {
			t.Fatalf("lookup %q, %v", v, ok)
		}
	})
	t.Run("an unset variable is gone", func(t *testing.T) {
		e, k := fresh(), key(t)
		if err := e.Setenv(k, "x"); err != nil {
			t.Fatal(err)
		}
		if err := e.Unsetenv(k); err != nil {
			t.Fatal(err)
		}
		if err := e.Unsetenv(k); err != nil {
			t.Fatalf("unsetting it again: %v", err)
		}
		if v, ok := e.LookupEnv(k); ok || e.Getenv(k) != "" {
			t.Fatalf("still %q", v)
		}
		for _, kv := range e.Environ() {
			if strings.HasPrefix(kv, k+"=") {
				t.Fatalf("environ still holds %s", kv)
			}
		}
	})
	t.Run("a name with = is refused", func(t *testing.T) {
		if err := fresh().Setenv("A=B", "x"); err == nil {
			t.Fatal("set a name holding =")
		}
	})
}
