package rules

import (
	"fmt"
	"go/parser"
	"go/token"
	"strings"
)

func init() {
	register(Rule{
		Name:    "test-package",
		Doc:     "a Go test file is in the external _test package, unless a comment above its package clause says why",
		Applies: func(path string) bool { return strings.HasSuffix(path, "_test.go") },
		Check:   testPackage,
	})
}

func testPackage(_ *Repo, path string, text []byte) []Finding {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, path, text, parser.PackageClauseOnly|parser.ParseComments)
	if err != nil {
		return []Finding{{Path: path, Line: 1, Rule: "test-package", Message: "no package clause: " + err.Error()}}
	}
	name := f.Name.Name
	if strings.HasSuffix(name, "_test") || f.Doc != nil {
		return nil
	}
	return []Finding{{
		Path: path, Line: fset.Position(f.Package).Line, Rule: "test-package",
		Message: fmt.Sprintf("package %s is internal; use package %s_test, or say why in a comment above the package clause", name, name),
	}}
}
