package rules_test

import "testing"

func TestAFakeWithoutAContractSuiteIsRefused(t *testing.T) {
	t.Parallel()
	suite := "package kept_test\n\nimport \"testing\"\n\nfunc contract(t *testing.T, fresh func() int) {}\n"
	found := check(t, "fake-contract", map[string]string{
		// Kept: the suite is called by the fake's test and the real one's.
		"src/modules/io/kept/fake.go":          "package kept\n\ntype Fake struct{}\n\nfunc NewFake() *Fake { return &Fake{} }\n",
		"src/modules/io/kept/contract_test.go": suite,
		"src/modules/io/kept/fake_test.go":     "package kept_test\n\nimport \"testing\"\n\nfunc TestFake(t *testing.T) { contract(t, nil) }\n",
		"src/modules/io/kept/real_test.go":     "package kept_test\n\nimport \"testing\"\n\nfunc TestReal(t *testing.T) { contract(t, nil) }\n",
		// No suite at all.
		"src/modules/io/bare/fake.go":      "package bare\n\n// Fake behaves.\ntype Fake struct{}\n",
		"src/modules/io/bare/fake_test.go": "package bare_test\n\nimport \"testing\"\n\nfunc TestFake(t *testing.T) {}\n",
		// The suite runs on the fake alone.
		"src/modules/io/half/doubles.go":       "package half\n\nfunc NewFake() int { return 0 }\n",
		"src/modules/io/half/contract_test.go": "package half_test\n\nimport \"testing\"\n\nfunc contract(t *testing.T, fresh func() int) {}\n",
		"src/modules/io/half/fake_test.go":     "package half_test\n\nimport \"testing\"\n\nfunc TestFake(t *testing.T) { contract(t, nil) }\n",
		"src/modules/io/half/real_test.go":     "package half_test\n\nimport \"testing\"\n\nfunc TestReal(t *testing.T) {}\n",
		// A test is no suite, though both call it.
		"src/modules/io/self/fake.go":      "package self\n\ntype Fake struct{}\n",
		"src/modules/io/self/fake_test.go": "package self_test\n\nimport \"testing\"\n\nfunc TestShared(t *testing.T) {}\n\nfunc TestFake(t *testing.T) { TestShared(t) }\n",
		"src/modules/io/self/real_test.go": "package self_test\n\nimport \"testing\"\n\nfunc TestReal(t *testing.T) { TestShared(t) }\n",
		// A module without a fake, and a fake outside the I/O modules, are not this rule's.
		"src/modules/io/plain/plain.go": "package plain\n\nfunc Real() int { return 0 }\n",
		"src/internal/other/fake.go":    "package other\n\ntype Fake struct{}\n",
	})
	same(t, found, []string{
		"src/modules/io/bare/fake.go:4: fake-contract: a fake without a contract suite",
		"src/modules/io/half/doubles.go:3: fake-contract: a fake without a contract suite",
		"src/modules/io/self/fake.go:3: fake-contract: a fake without a contract suite",
	})
}
