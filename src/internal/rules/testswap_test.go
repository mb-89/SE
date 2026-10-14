package rules_test

import "testing"

func TestATestSwappingAPackageFuncVariableIsRefused(t *testing.T) {
	t.Parallel()
	found := check(t, "test-swap", map[string]string{
		"go.mod": "module example.com/m\n\ngo 1.24\n",
		"a/a.go": "package a\n\nimport \"os\"\n\n" +
			"var executable = os.Executable\n" +
			"var check = func() error { return nil }\n" +
			"var Hook func()\n" +
			"var clock = newClock()\n" +
			"var count = 3\n" +
			"var on = true\n\n" +
			"func newClock() int { return 0 }\n",
		// An internal test swaps its own package's.
		"a/a_test.go": "// Internal: it swaps.\npackage a\n\nimport \"testing\"\n\n" +
			"func TestSwaps(t *testing.T) {\n" +
			"\twas := executable\n" +
			"\texecutable = func() (string, error) { return \"se\", nil }\n" +
			"\tt.Cleanup(func() { executable = was })\n" +
			"\tcheck = nil\n" +
			"\tclock, count, on = 1, 4, false\n" +
			"}\n\n" +
			"func TestShadows(t *testing.T) {\n" +
			"\tvar check func() error\n" +
			"\tcheck = nil\n" +
			"\t_ = check\n" +
			"}\n\n" +
			"func helper(executable func() (string, error)) { executable = nil; _ = executable }\n",
		// An external test swaps an exported one through its import.
		"a/b_test.go": "package a_test\n\nimport (\n\t\"testing\"\n\n\tx \"example.com/m/a\"\n)\n\n" +
			"func TestSwapsHook(t *testing.T) { x.Hook = func() {} }\n",
		// Its own variables a test may set.
		"b/b_test.go": "package b_test\n\nimport \"testing\"\n\nvar hook func()\n\nfunc TestOwn(t *testing.T) { hook = func() {} }\n",
	})
	same(t, found, []string{
		"a/a_test.go:8: test-swap: executable is a package-level func variable",
		"a/a_test.go:9: test-swap: executable is a package-level func variable",
		"a/a_test.go:10: test-swap: check is a package-level func variable",
		"a/b_test.go:9: test-swap: x.Hook is a package-level func variable",
	})
}
