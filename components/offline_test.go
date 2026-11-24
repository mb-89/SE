package components_test

import (
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path"
	"sort"
	"strconv"
	"strings"
	"testing"
	"testing/fstest"

	// This test binary, too, runs with the network cut.
	_ "kern/offline"
)

// SE's Go suite runs with the network cut (components/README.md "Tests"):
// every folder of this module with a _test.go imports kern/offline in one of
// them, so its test binary cuts itself off the network at init, as kern's
// own suite does (kern's README "Tests").

// uncut answers each folder of fsys that holds a _test.go and none that
// imports kern/offline, sorted. It skips the folders .se, .git and testdata,
// and each folder with a go.mod of its own, another module.
func uncut(fsys fs.FS) ([]string, error) {
	tests, cut := map[string]bool{}, map[string]bool{}
	err := fs.WalkDir(fsys, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			switch d.Name() {
			case ".se", ".git", "testdata":
				return fs.SkipDir
			}
			if _, err := fs.Stat(fsys, path.Join(p, "go.mod")); err == nil && p != "." {
				return fs.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(p, "_test.go") {
			return nil
		}
		dir := path.Dir(p)
		tests[dir] = true
		src, err := fs.ReadFile(fsys, p)
		if err != nil {
			return err
		}
		f, err := parser.ParseFile(token.NewFileSet(), p, src, parser.ImportsOnly)
		if err != nil {
			return err
		}
		for _, imp := range f.Imports {
			if v, _ := strconv.Unquote(imp.Path.Value); v == "kern/offline" {
				cut[dir] = true
			}
		}
		return nil
	})
	var out []string
	for dir := range tests {
		if !cut[dir] {
			out = append(out, dir)
		}
	}
	sort.Strings(out)
	return out, err
}

func TestEveryPackageWithTestsRunsWithTheNetworkCut(t *testing.T) {
	missing, err := uncut(os.DirFS("."))
	if err != nil {
		t.Fatal(err)
	}
	if len(missing) > 0 {
		t.Fatalf("these folders hold tests and import no kern/offline, so their test binaries reach the network: %v; add an offline_test.go with `import _ \"kern/offline\"`", missing)
	}
}

// The check finds a folder whose tests import no kern/offline, and leaves
// testdata, .se and another module's folders alone.
func TestTheCheckNamesAnUncutFolder(t *testing.T) {
	fsys := fstest.MapFS{
		"cut/a_test.go":              {Data: []byte("package cut\n\nimport _ \"kern/offline\"\n")},
		"cut/b_test.go":              {Data: []byte("package cut\n")},
		"open/a_test.go":             {Data: []byte("package open\n\nimport \"testing\"\n")},
		"open/a.go":                  {Data: []byte("package open\n")},
		"testdata/x/a_test.go":       {Data: []byte("package x\n")},
		".se/modules/kern/a_test.go": {Data: []byte("package kern\n")},
		"other/go.mod":               {Data: []byte("module other\n")},
		"other/a_test.go":            {Data: []byte("package other\n")},
	}
	got, err := uncut(fsys)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(got, ",") != "open" {
		t.Fatalf("the check names %v, and wants [open]", got)
	}
}
