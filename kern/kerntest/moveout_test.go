package kerntest_test

import (
	"bufio"
	"bytes"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
	"testing/fstest"
)

// The move-out report: everything under kern/ that names SE or one host,
// the to-do list for the day kern moves to its own repository. Its patterns
// are testdata/names-patterns.txt, the list as it stands testdata/
// names-se-or-host.txt. The test passes and logs the list (go test -v -run
// MoveOut ./kerntest); an entry the list lacks, or one it holds that is gone,
// is a notice, never a failure. -update rewrites the list from the tree.

var updateMoveOut = flag.Bool("update", false, "rewrite testdata/names-se-or-host.txt from the tree")

const (
	patternsFile = "testdata/names-patterns.txt"
	listFile     = "testdata/names-se-or-host.txt"
)

// moveOutPattern is one line of the patterns file: a kind and its regexp.
type moveOutPattern struct {
	kind string
	re   *regexp.Regexp
}

// moveOutEntry is one place that names SE or a host: its kind, its file
// relative to kern/ (slash-separated) and the text matched.
type moveOutEntry struct{ kind, file, match string }

func (e moveOutEntry) String() string { return e.kind + "\t" + e.file + "\t" + e.match }

// moveOutSkipped are the files the scan never reads, by their path under
// kern/: the report's own test and data, which name what they look for.
var moveOutSkipped = map[string]bool{
	"kerntest/moveout_test.go": true,
	"kerntest/" + patternsFile: true,
	"kerntest/" + listFile:     true,
}

// dataLines answers a data file's lines without blank and # comment lines,
// a Windows checkout's \r trimmed.
func dataLines(text string) []string {
	var lines []string
	for _, l := range strings.Split(text, "\n") {
		l = strings.TrimSpace(strings.TrimRight(l, "\r"))
		if l != "" && !strings.HasPrefix(l, "#") {
			lines = append(lines, l)
		}
	}
	return lines
}

// parseMoveOutPatterns reads the patterns file: a kind, whitespace, a regexp.
func parseMoveOutPatterns(text string) ([]moveOutPattern, error) {
	var ps []moveOutPattern
	for _, l := range dataLines(text) {
		fields := strings.Fields(l)
		if len(fields) < 2 {
			return nil, fmt.Errorf("pattern line %q has no regexp", l)
		}
		re, err := regexp.Compile(strings.TrimSpace(strings.TrimPrefix(l, fields[0])))
		if err != nil {
			return nil, fmt.Errorf("pattern line %q: %w", l, err)
		}
		ps = append(ps, moveOutPattern{fields[0], re})
	}
	return ps, nil
}

// parseMoveOutList reads the list file: kind, file and match, tab-separated.
func parseMoveOutList(text string) (map[moveOutEntry]bool, error) {
	list := map[moveOutEntry]bool{}
	for _, l := range dataLines(text) {
		f := strings.SplitN(l, "\t", 3)
		if len(f) != 3 {
			return nil, fmt.Errorf("list line %q is not kind, file and match, tab-separated", l)
		}
		list[moveOutEntry{f[0], f[1], f[2]}] = true
	}
	return list, nil
}

// scanMoveOut walks fsys and answers every place a pattern names, each
// distinct kind, file and match once, sorted. On a line, a span the first
// matching pattern claims is never listed again under a later one. Folders
// .git and __pycache__, files with a NUL byte and the skipped files are not
// read.
func scanMoveOut(fsys fs.FS, patterns []moveOutPattern, skipped map[string]bool) ([]moveOutEntry, error) {
	found := map[moveOutEntry]bool{}
	err := fs.WalkDir(fsys, ".", func(name string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if d.Name() == ".git" || d.Name() == "__pycache__" {
				return fs.SkipDir
			}
			return nil
		}
		if skipped[name] {
			return nil
		}
		data, err := fs.ReadFile(fsys, name)
		if err != nil {
			return err
		}
		if bytes.IndexByte(data, 0) >= 0 {
			return nil
		}
		lines := bufio.NewScanner(bytes.NewReader(data))
		lines.Buffer(make([]byte, 0, 64*1024), len(data)+1)
		for lines.Scan() {
			line := lines.Text()
			var claimed [][2]int
			for _, p := range patterns {
				for _, at := range p.re.FindAllStringIndex(line, -1) {
					if overlaps(claimed, at) {
						continue
					}
					claimed = append(claimed, [2]int{at[0], at[1]})
					found[moveOutEntry{p.kind, name, line[at[0]:at[1]]}] = true
				}
			}
		}
		return lines.Err()
	})
	if err != nil {
		return nil, err
	}
	entries := make([]moveOutEntry, 0, len(found))
	for e := range found {
		entries = append(entries, e)
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].String() < entries[j].String() })
	return entries, nil
}

func overlaps(claimed [][2]int, at []int) bool {
	for _, c := range claimed {
		if at[0] < c[1] && c[0] < at[1] {
			return true
		}
	}
	return false
}

// diffMoveOut answers the entries found that the list lacks and those it
// holds that are no longer found, each sorted.
func diffMoveOut(found []moveOutEntry, list map[moveOutEntry]bool) (added, gone []moveOutEntry) {
	seen := map[moveOutEntry]bool{}
	for _, e := range found {
		seen[e] = true
		if !list[e] {
			added = append(added, e)
		}
	}
	for e := range list {
		if !seen[e] {
			gone = append(gone, e)
		}
	}
	sort.Slice(gone, func(i, j int) bool { return gone[i].String() < gone[j].String() })
	return added, gone
}

// reportMoveOut writes the list grouped by kind, in the patterns' order:
// each kind with its count, then each file with the matches it holds.
func reportMoveOut(found []moveOutEntry, patterns []moveOutPattern) string {
	byKind := map[string]map[string][]string{}
	for _, e := range found {
		if byKind[e.kind] == nil {
			byKind[e.kind] = map[string][]string{}
		}
		byKind[e.kind][e.file] = append(byKind[e.kind][e.file], e.match)
	}
	var b strings.Builder
	done := map[string]bool{}
	for _, p := range patterns {
		files := byKind[p.kind]
		if done[p.kind] || files == nil {
			continue
		}
		done[p.kind] = true
		names := make([]string, 0, len(files))
		for f := range files {
			names = append(names, f)
		}
		sort.Strings(names)
		fmt.Fprintf(&b, "%s (%d files)\n", p.kind, len(names))
		for _, f := range names {
			fmt.Fprintf(&b, "  %s: %s\n", f, strings.Join(files[f], ", "))
		}
	}
	return b.String()
}

// listText is the list file's content for the entries found.
func listText(found []moveOutEntry) string {
	var b strings.Builder
	b.WriteString("# Everything under kern/ that names SE or one host, as it stands: kind, file, match,\n")
	b.WriteString("# tab-separated. moveout_test.go writes it with -update and reports what differs.\n")
	for _, e := range found {
		b.WriteString(e.String() + "\n")
	}
	return b.String()
}

func readMoveOutPatterns(t *testing.T) []moveOutPattern {
	t.Helper()
	text, err := os.ReadFile(filepath.FromSlash(patternsFile))
	if err != nil {
		t.Fatal(err)
	}
	ps, err := parseMoveOutPatterns(string(text))
	if err != nil {
		t.Fatal(err)
	}
	return ps
}

// kern/ as it stands, against the list: the test logs the list grouped by
// kind and a notice for each entry new or gone, and passes.
func TestMoveOutListsWhatNamesSEOrAHost(t *testing.T) {
	patterns := readMoveOutPatterns(t)
	found, err := scanMoveOut(os.DirFS(".."), patterns, moveOutSkipped)
	if err != nil {
		t.Fatal(err)
	}
	if *updateMoveOut {
		if err := os.WriteFile(filepath.FromSlash(listFile), []byte(listText(found)), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	text, err := os.ReadFile(filepath.FromSlash(listFile))
	if err != nil {
		t.Fatal(err)
	}
	list, err := parseMoveOutList(string(text))
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("what kern/ names of SE or one host, %d entries:\n%s", len(found), reportMoveOut(found, patterns))
	added, gone := diffMoveOut(found, list)
	for _, e := range added {
		t.Logf("notice: new, not in %s: %s", listFile, e)
	}
	for _, e := range gone {
		t.Logf("notice: gone, still in %s: %s", listFile, e)
	}
}

// A reference planted in a fixture tree is reported as new, a listed one no
// longer there as gone, a span is listed under its first kind only, and the
// skipped, binary and __pycache__ files are not read.
func TestMoveOutReportsAPlantedReference(t *testing.T) {
	patterns := readMoveOutPatterns(t)
	tree := fstest.MapFS{
		"a/a.go":               {Data: []byte("package a\n// see ../docs/go-core.md#x and $SE_GIT_DOOR\n")},
		"a/README.md":          {Data: []byte("uses: mb-89/SE/.github/workflows/kern-battery.yml@kern-v1\r\n")},
		"b/b.go":               {Data: []byte("package b\n")},
		"b/__pycache__/b.pyc":  {Data: []byte("SE_GIT_DOOR")},
		"b/bin":                {Data: []byte("SE_GIT_DOOR\x00")},
		"kerntest/" + listFile: {Data: []byte("SE_GIT_DOOR")},
	}
	listed, err := parseMoveOutList("# a comment\nse-doc-link\ta/a.go\t../docs/go-core.md#x\nse-variable\tb/b.go\tSE_OLD\n")
	if err != nil {
		t.Fatal(err)
	}
	found, err := scanMoveOut(tree, patterns, moveOutSkipped)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, e := range found {
		got = append(got, e.String())
	}
	want := []string{
		"se-doc-link\ta/a.go\t../docs/go-core.md#x",
		"se-variable\ta/a.go\tSE_GIT_DOOR",
		"se-workflow\ta/README.md\tmb-89/SE/.github/workflows/kern-battery.yml@kern-v1",
	}
	sort.Strings(want)
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("the scan answers\n%s\nand wants\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	added, gone := diffMoveOut(found, listed)
	if len(added) != 2 || added[0].match != "SE_GIT_DOOR" || added[1].kind != "se-workflow" {
		t.Fatalf("new entries %v, want the planted variable and workflow", added)
	}
	if len(gone) != 1 || gone[0] != (moveOutEntry{"se-variable", "b/b.go", "SE_OLD"}) {
		t.Fatalf("gone entries %v, want b/b.go's SE_OLD", gone)
	}
	if r := reportMoveOut(found, patterns); !strings.HasPrefix(r, "se-workflow (1 files)\n  a/README.md: ") {
		t.Fatalf("the report starts %q, want the workflow kind first, as the patterns order it", r)
	}
}

// A pattern line without a regexp, or with one that does not compile, and a
// list line that is not three tab-separated fields are refused, named.
func TestMoveOutRefusesMalformedData(t *testing.T) {
	for _, text := range []string{"se-name\n", "se-name (\n"} {
		if _, err := parseMoveOutPatterns(text); err == nil {
			t.Errorf("patterns %q pass, want refused", text)
		}
	}
	if _, err := parseMoveOutList("se-name only-two\n"); err == nil {
		t.Error("a list line of one field passes, want refused")
	}
}
