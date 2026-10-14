package rules_test

import (
	"strings"
	"testing"
)

func TestAFakeHasItsContractSuite(t *testing.T) {
	found := check(t, "fake-contract", map[string]string{
		"src/internal/io/clock/fake.go":          "package clock\n",
		"src/internal/io/clock/contract_test.go": "package clock_test\n",
		"src/internal/io/disk/fake.go":           "package disk\n",
		"src/internal/io/disk/fake_test.go":      "package disk_test\n",
		"src/internal/other/fake.go":             "package other\n",
	})
	want := "src/internal/io/disk/fake.go:1: fake-contract: a fake without its contract suite"
	if len(found) != 1 || !strings.HasPrefix(found[0], want) {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
}
