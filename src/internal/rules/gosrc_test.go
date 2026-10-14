package rules_test

import (
	"sort"
	"strings"
	"testing"
)

func TestAGoCommandRunsFromSrc(t *testing.T) {
	t.Parallel()
	found := check(t, "go-in-src", map[string]string{
		".github/workflows/a.yml":  "      - run: go test ./...\n      - run: go -C src test ./...\n      - uses: actions/setup-go@v5\n        with:\n          go-version-file: src/go.mod\n",
		".github/workflows/b.yaml": "      - run: cd x && go vet ./...\n",
		"tests/check.sh":           "# go test in a comment\nstep \"go test\" go -C src run ./cmd/battery\ngo run ./cmd/se\n",
		"tests/tools.sh":           "gopath=$(go env GOPATH)\nGOBIN=$b go install \"example.com/x@v$V\"\ncommand -v go >/dev/null\necho \"go $GO\"\n",
		"src/build.sh":             "go -C \"$src\" build -o \"$out\" ./cmd/se\ngo build ./cmd/se\n",
		"src/scripts/x.sh":         "go -C \"$root/src\" test ./...\ngo -C other test ./...\n",
		"src/cmd/x.go":             "package x // go test ./...\n",
		"RUNME.md":                 "go test ./...\n",
	})
	want := ".github/workflows/a.yml:1|.github/workflows/b.yaml:1|src/build.sh:2|src/scripts/x.sh:2|tests/check.sh:3"
	var got []string
	for _, f := range found {
		got = append(got, f[:strings.Index(f, ": go-in-src")])
	}
	sort.Strings(got)
	if strings.Join(got, "|") != want {
		t.Fatalf("found:\n%s", strings.Join(found, "\n"))
	}
}
