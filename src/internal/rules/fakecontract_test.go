package rules_test

import "testing"

func TestAFakeWithoutAContractSuiteIsRefused(t *testing.T) {
	suite := "package kept_test\n\nimport \"testing\"\n\nfunc contract(t *testing.T, fresh func() int) {}\n"
	found := check(t, "fake-contract", map[string]string{
		// Kept: the suite is called by the fake's test and the real one's.
		"src/internal/io/kept/fake.go":          "package kept\n\ntype Fake struct{}\n\nfunc NewFake() *Fake { return &Fake{} }\n",
		"src/internal/io/kept/contract_test.go": suite,
		"src/internal/io/kept/fake_test.go":     "package kept_test\n\nimport \"testing\"\n\nfunc TestFake(t *testing.T) { contract(t, nil) }\n",
		"src/internal/io/kept/real_test.go":     "package kept_test\n\nimport \"testing\"\n\nfunc TestReal(t *testing.T) { contract(t, nil) }\n",
		// No suite at all.
		"src/internal/io/bare/fake.go":      "package bare\n\n// Fake behaves.\ntype Fake struct{}\n",
		"src/internal/io/bare/fake_test.go": "package bare_test\n\nimport \"testing\"\n\nfunc TestFake(t *testing.T) {}\n",
		// The suite runs on the fake alone.
		"src/internal/io/half/doubles.go":       "package half\n\nfunc NewFake() int { return 0 }\n",
		"src/internal/io/half/contract_test.go": "package half_test\n\nimport \"testing\"\n\nfunc contract(t *testing.T, fresh func() int) {}\n",
		"src/internal/io/half/fake_test.go":     "package half_test\n\nimport \"testing\"\n\nfunc TestFake(t *testing.T) { contract(t, nil) }\n",
		"src/internal/io/half/real_test.go":     "package half_test\n\nimport \"testing\"\n\nfunc TestReal(t *testing.T) {}\n",
		// A test is no suite, though both call it.
		"src/internal/io/self/fake.go":      "package self\n\ntype Fake struct{}\n",
		"src/internal/io/self/fake_test.go": "package self_test\n\nimport \"testing\"\n\nfunc TestShared(t *testing.T) {}\n\nfunc TestFake(t *testing.T) { TestShared(t) }\n",
		"src/internal/io/self/real_test.go": "package self_test\n\nimport \"testing\"\n\nfunc TestReal(t *testing.T) { TestShared(t) }\n",
		// A module without a fake, and a fake outside the I/O modules, are not this rule's.
		"src/internal/io/plain/plain.go": "package plain\n\nfunc Real() int { return 0 }\n",
		"src/internal/other/fake.go":     "package other\n\ntype Fake struct{}\n",
	})
	same(t, found, []string{
		"src/internal/io/bare/fake.go:4: fake-contract: a fake without a contract suite",
		"src/internal/io/half/doubles.go:3: fake-contract: a fake without a contract suite",
		"src/internal/io/self/fake.go:3: fake-contract: a fake without a contract suite",
	})
}
