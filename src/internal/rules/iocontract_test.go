package rules_test

import "testing"

func TestEveryIOModuleRunsItsContractSuiteAgainstFakeAndReal(t *testing.T) {
	const (
		suite = "package m_test\n\nimport \"testing\"\n\nfunc contract(t *testing.T, fresh func()) {}\n"
		run   = "package m_test\n\nimport \"testing\"\n\nfunc TestIt(t *testing.T) { contract(t, nil) }\n"
		skip  = "package m_test\n\nimport \"testing\"\n\nfunc TestIt(t *testing.T) {}\n"
	)
	found := check(t, "io-contract", map[string]string{
		// Kept: fake, suite, and both sides run it; checked once though it has two files.
		"src/internal/io/kept/kept.go":          "package kept\n",
		"src/internal/io/kept/fake.go":          "package kept\n",
		"src/internal/io/kept/contract_test.go": suite,
		"src/internal/io/kept/fake_test.go":     run,
		"src/internal/io/kept/real_test.go":     run,
		// A fake whose suite runs against the fake alone.
		"src/internal/io/half/half.go":          "package half\n",
		"src/internal/io/half/fake.go":          "package half\n",
		"src/internal/io/half/contract_test.go": suite,
		"src/internal/io/half/fake_test.go":     run,
		"src/internal/io/half/real_test.go":     skip,
		// A fake with no suite at all.
		"src/internal/io/bare/bare.go":      "package bare\n",
		"src/internal/io/bare/fake.go":      "package bare\n",
		"src/internal/io/bare/fake_test.go": skip,
		// No fake: its suite runs against the real one alone.
		"src/internal/io/lone/lone.go":          "package lone\n",
		"src/internal/io/lone/contract_test.go": suite,
		"src/internal/io/lone/real_test.go":     run,
		// Not modules.
		"src/internal/io/allowlist.txt": "",
		"src/internal/io/x/y/deep.go":   "package y\n",
		"src/internal/other/fake.go":    "package other\n",
	})
	same(t, found, []string{
		"src/internal/io/half/fake.go:1: io-contract: the I/O module src/internal/io/half does not run its contract suite against the real one",
		"src/internal/io/bare/bare.go:1: io-contract: the I/O module src/internal/io/bare has no contract suite",
		"src/internal/io/bare/bare.go:1: io-contract: the I/O module src/internal/io/bare does not run its contract suite against the fake one",
		"src/internal/io/bare/bare.go:1: io-contract: the I/O module src/internal/io/bare does not run its contract suite against the real one",
		"src/internal/io/lone/lone.go:1: io-contract: the I/O module src/internal/io/lone has no fake",
		"src/internal/io/lone/lone.go:1: io-contract: the I/O module src/internal/io/lone does not run its contract suite against the fake one",
	})
}
