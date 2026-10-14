package rules_test

import (
	"strings"
	"testing"
)

func TestTheTreeTracksNoLargeFileButThoseListed(t *testing.T) {
	t.Parallel()
	big := strings.Repeat("x", 1<<20+1)
	found := check(t, "large-file", map[string]string{
		"src/se":                       big,
		"assets/kept.bin":              big,
		"a.go":                         "package a\n",
		"edge.txt":                     strings.Repeat("x", 1<<20),
		"src/internal/rules/large.txt": "# kept\nassets/kept.bin\nedge.txt\ngone.bin\n",
	})
	same(t, found, []string{
		"src/internal/rules/large.txt:3: large-file: the entry names no file over the bound: edge.txt",
		"src/internal/rules/large.txt:4: large-file: the entry names no file over the bound: gone.bin",
		"src/se:1: large-file: 1048577 bytes, over 1048576",
	})
}
