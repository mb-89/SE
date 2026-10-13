package rules_test

import (
	"strings"
	"testing"
)

func TestATestFileIsInTheExternalPackage(t *testing.T) {
	found := check(t, "test-package", map[string]string{
		"a/a_test.go":   "package a_test\n",
		"b/b_test.go":   "// Internal test package: it drives the unexported step.\npackage b\n",
		"c/c_test.go":   "// Copyright nobody\n\npackage c\n",
		"d/d.go":        "package d\n",
		"e/e_test.go":   "\n\npackage e\n",
		"f/f_test.go":   "not go at all",
		"g/notes.md":    "package g",
		"h/h_test.go":   "/* Internal: it says why. */\npackage h\n",
		"i/i_test.go":   "//go:build linux\n\npackage i\n",
		"j/j_test.go":   "package j // a comment after the clause is no reason\n",
		"k/k_more.go":   "package k\n",
		"l/l_test.go":   "package l_test\n\nfunc TestX() {}\n",
		"m/doc_test.go": "// Internal test package: package main cannot be imported.\npackage main\n",
	})
	want := []string{
		"c/c_test.go:3: test-package: package c is internal; use package c_test, or say why in a comment above the package clause",
		"e/e_test.go:3: test-package: package e is internal; use package e_test, or say why in a comment above the package clause",
		"f/f_test.go:1: test-package: no package clause",
		"i/i_test.go:3: test-package: package i is internal; use package i_test, or say why in a comment above the package clause",
		"j/j_test.go:1: test-package: package j is internal; use package j_test, or say why in a comment above the package clause",
	}
	if len(found) != len(want) {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
	for _, w := range want {
		hit := false
		for _, f := range found {
			hit = hit || strings.HasPrefix(f, w)
		}
		if !hit {
			t.Errorf("missing %q in:\n%s", w, strings.Join(found, "\n"))
		}
	}
}
