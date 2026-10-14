package rules

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"strings"
	"unicode"
)

// ioRoot is the folder every I/O module is a package under.
const ioRoot = "src/internal/io/"

func init() {
	register(Rule{
		Name: "fake-contract",
		Doc: "a fake under " + ioRoot + "<name> has a contract suite: a function in a test file of its package, " +
			"called by a test in fake_test.go and by one in real_test.go",
		Applies: func(p string) bool {
			return strings.HasPrefix(p, ioRoot) && path.Ext(p) == ".go" && !strings.HasSuffix(p, "_test.go") &&
				strings.Count(strings.TrimPrefix(p, ioRoot), "/") == 1
		},
		Check: fakeContract,
	})
}

// fakeContract refuses a file declaring a fake, the type Fake or NewFake,
// whose package keeps no contract suite both the fake's test and the real
// one's call.
func fakeContract(repo *Repo, p string, text []byte) []Finding {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	at := fakeDecl(f)
	if !at.IsValid() {
		return nil
	}
	dir := path.Dir(p)
	declared := map[string]bool{} // the functions the package's test files declare, tests aside
	calledIn := map[string]map[string]bool{}
	for _, q := range repo.Paths {
		if path.Dir(q) != dir || !strings.HasSuffix(q, "_test.go") {
			continue
		}
		t, ok, err := repo.Read(q)
		if err != nil || !ok {
			continue
		}
		tf, err := parser.ParseFile(token.NewFileSet(), q, t, parser.SkipObjectResolution)
		if err != nil {
			continue
		}
		calls := map[string]bool{}
		for _, d := range tf.Decls {
			fn, ok := d.(*ast.FuncDecl)
			if !ok || fn.Recv != nil {
				continue
			}
			if !isTestFunc(fn.Name.Name) {
				declared[fn.Name.Name] = true
				continue
			}
			ast.Inspect(fn, func(n ast.Node) bool {
				if c, ok := n.(*ast.CallExpr); ok {
					if id, ok := c.Fun.(*ast.Ident); ok {
						calls[id.Name] = true
					}
				}
				return true
			})
		}
		calledIn[path.Base(q)] = calls
	}
	for name := range declared {
		if calledIn["fake_test.go"][name] && calledIn["real_test.go"][name] {
			return nil
		}
	}
	return []Finding{{
		Path: p, Line: fset.Position(at).Line, Rule: "fake-contract",
		Message: "a fake without a contract suite: write one function in a _test.go file of " + dir +
			" and call it from a test in fake_test.go and from one in real_test.go (spec/io.md)",
	}}
}

// fakeDecl answers where the file declares its fake, the type Fake or the
// function NewFake, whichever comes first; NoPos where it declares neither.
func fakeDecl(f *ast.File) token.Pos {
	for _, d := range f.Decls {
		switch d := d.(type) {
		case *ast.FuncDecl:
			if d.Recv == nil && d.Name.Name == "NewFake" {
				return d.Pos()
			}
		case *ast.GenDecl:
			for _, s := range d.Specs {
				if ts, ok := s.(*ast.TypeSpec); ok && ts.Name.Name == "Fake" {
					return ts.Pos()
				}
			}
		}
	}
	return token.NoPos
}

// isTestFunc says whether a function is one go test runs itself: TestX,
// BenchmarkX, ExampleX, FuzzX, or TestMain.
func isTestFunc(name string) bool {
	for _, prefix := range []string{"Test", "Benchmark", "Example", "Fuzz"} {
		if rest, ok := strings.CutPrefix(name, prefix); ok && (rest == "" || !unicode.IsLower(rune(rest[0]))) {
			return true
		}
	}
	return false
}
