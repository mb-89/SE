// Internal test package: package main cannot be imported.
package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRulesFixWritesTheMechanicalPartAndChecksTheRest(t *testing.T) {
	t.Parallel()
	ws := prose(t, map[string]string{
		"src/a/a_test.go": "package a_test\n\nimport \"testing\"\n\nfunc TestA(t *testing.T) {\n\tt.Log()\n}\n",
	})
	if code, _, errs := se(t, "--workspace", ws, "rules"); code != 1 || !strings.Contains(errs, "src/a/a_test.go:5: fast-test: TestA does not call t.Parallel first") {
		t.Fatalf("rules (exit %d): %s", code, errs)
	}
	code, out, errs := se(t, "--workspace", ws, "rules", "--fix")
	if code != 0 || !strings.Contains(out, "fixed: src/a/a_test.go: fast-test\n") {
		t.Fatalf("rules --fix (exit %d): %s %s", code, out, errs)
	}
	data, _ := os.ReadFile(filepath.Join(ws, "src", "a", "a_test.go"))
	if !strings.Contains(string(data), "func TestA(t *testing.T) {\n\tt.Parallel()\n\tt.Log()\n}\n") {
		t.Fatalf("a_test.go:\n%s", data)
	}
	if code, out, _ := se(t, "--workspace", ws, "rules", "--fix"); code != 0 || strings.Contains(out, "fixed:") {
		t.Fatalf("a second fix (exit %d): %s", code, out)
	}
}
