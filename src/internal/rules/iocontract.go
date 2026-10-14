package rules

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"strings"
)

func init() {
	register(Rule{
		Name: "io-contract",
		Doc: "every I/O module under src/internal/io has a fake (fake.go) and one contract suite (func contract in contract_test.go) " +
			"that both fake_test.go and real_test.go call",
		Applies: func(p string) bool { return moduleOf(p) != "" },
		Check:   ioContract,
	})
}

// moduleOf answers the I/O module folder a non-test Go file sits directly in,
// such as src/internal/io/clock, or "" for any other file.
func moduleOf(p string) string {
	dir := path.Dir(p)
	if path.Ext(p) != ".go" || strings.HasSuffix(p, "_test.go") || path.Dir(dir) != "src/internal/io" {
		return ""
	}
	return dir
}

// ioContract checks the module once, on its first non-test Go file by name.
func ioContract(repo *Repo, p string, _ []byte) []Finding {
	mod := moduleOf(p)
	for _, other := range repo.Paths {
		if moduleOf(other) == mod && other < p {
			if _, ok, _ := repo.Read(other); ok {
				return nil
			}
		}
	}
	var found []Finding
	refuse := func(msg string) {
		found = append(found, Finding{Path: p, Line: 1, Rule: "io-contract", Message: "the I/O module " + mod + " " + msg + " (spec/io.md)"})
	}
	if _, ok, _ := repo.Read(mod + "/fake.go"); !ok {
		refuse("has no fake: write it in fake.go")
	}
	if !declaresContract(repo, mod+"/contract_test.go") {
		refuse("has no contract suite: write func contract in contract_test.go")
	}
	for _, side := range []string{"fake", "real"} {
		if !callsContract(repo, mod+"/"+side+"_test.go") {
			refuse("does not run its contract suite against the " + side + " one: call contract in " + side + "_test.go")
		}
	}
	return found
}

// parsed answers the Go file at p, or nil where it is missing or does not parse.
func parsed(repo *Repo, p string) *ast.File {
	text, ok, _ := repo.Read(p)
	if !ok {
		return nil
	}
	f, err := parser.ParseFile(token.NewFileSet(), p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	return f
}

func declaresContract(repo *Repo, p string) bool {
	f := parsed(repo, p)
	if f == nil {
		return false
	}
	for _, d := range f.Decls {
		if fn, ok := d.(*ast.FuncDecl); ok && fn.Recv == nil && fn.Name.Name == "contract" {
			return true
		}
	}
	return false
}

func callsContract(repo *Repo, p string) bool {
	f := parsed(repo, p)
	if f == nil {
		return false
	}
	hit := false
	ast.Inspect(f, func(n ast.Node) bool {
		if call, ok := n.(*ast.CallExpr); ok {
			if id, ok := call.Fun.(*ast.Ident); ok && id.Name == "contract" {
				hit = true
			}
		}
		return !hit
	})
	return hit
}
