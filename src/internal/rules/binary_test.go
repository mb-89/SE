package rules_test

import (
	"sort"
	"strings"
	"testing"
)

func TestTheTreeTracksNoCompiledProgram(t *testing.T) {
	t.Parallel()
	found := check(t, "no-binary", map[string]string{
		"src/se":    "\x7fELF\x02\x01\x01\x00",
		"bin/mac":   "\xcf\xfa\xed\xfe\x07\x00",
		"bin/fat":   "\xca\xfe\xba\xbe\x00",
		"a.go":      "package a\n",
		"logo.png":  "\x89PNG\r\n",
		"notes.txt": "ELF is not at the start\n",
		"empty.txt": "",
	})
	sort.Strings(found)
	want := "bin/fat:1: no-binary|bin/mac:1: no-binary|src/se:1: no-binary"
	var got []string
	for _, f := range found {
		got = append(got, f[:strings.Index(f, "no-binary")+len("no-binary")])
	}
	if strings.Join(got, "|") != want {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
}
