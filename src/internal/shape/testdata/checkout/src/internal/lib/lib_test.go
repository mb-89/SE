package lib_test

import (
	"testing"

	"example.com/fix/internal/lib"
	"example.com/fix/internal/libtest"
)

func TestOnlyTests(t *testing.T) {
	t.Parallel()
	if lib.OnlyTests() != libtest.Seven() {
		t.Fatal("not seven")
	}
}
