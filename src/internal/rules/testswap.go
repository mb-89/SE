package rules

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"strconv"
	"strings"
)

func init() {
	register(Rule{
		Name: "test-swap",
		Doc: "a Go test assigns no package-level func variable, its own package's or one it imports: " +
			"it hands the outside in through an I/O module",
		Applies: func(p string) bool { return strings.HasSuffix(p, "_test.go") },
		Check:   testSwap,
	})
}

// testSwap refuses every assignment, in a test file, to a package-level func
// variable declared outside the test files: the test swapping how a package
// reaches the outside, where it should hand in a fake.
func testSwap(repo *Repo, p string, text []byte) []Finding {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	own := map[string]bool{}
	if !strings.HasSuffix(f.Name.Name, "_test") {
		own = funcVars(repo, path.Dir(p), false)
	}
	imported := map[string]map[string]bool{} // by the name a package goes by in the file
	module := modulePath(repo)
	for _, im := range f.Imports {
		ip, _ := strconv.Unquote(im.Path.Value)
		rel, ok := strings.CutPrefix(ip, module+"/")
		if module == "" || !ok {
			continue
		}
		name := path.Base(ip)
		if im.Name != nil {
			name = im.Name.Name
		}
		imported[name] = funcVars(repo, rel, true)
	}
	var found []Finding
	refuse := func(name string, at token.Pos) {
		found = append(found, Finding{
			Path: p, Line: fset.Position(at).Line, Rule: "test-swap",
			Message: name + " is a package-level func variable the test swaps; hand the outside in through an I/O module " +
				"as an argument or a field instead (spec/io.md)",
		})
	}
	for _, d := range f.Decls {
		fn, ok := d.(*ast.FuncDecl)
		if !ok || fn.Body == nil {
			continue
		}
		local := declaredIn(fn)
		ast.Inspect(fn.Body, func(n ast.Node) bool {
			as, ok := n.(*ast.AssignStmt)
			if !ok || as.Tok != token.ASSIGN {
				return true
			}
			for _, lhs := range as.Lhs {
				switch l := lhs.(type) {
				case *ast.Ident:
					if own[l.Name] && !local[l.Name] {
						refuse(l.Name, l.Pos())
					}
				case *ast.SelectorExpr:
					if x, ok := l.X.(*ast.Ident); ok && !local[x.Name] && imported[x.Name][l.Sel.Name] {
						refuse(x.Name+"."+l.Sel.Name, l.Pos())
					}
				}
			}
			return true
		})
	}
	return found
}

// funcVars answers the package-level func variables the non-test Go files
// in dir declare, only the exported ones if exported: a variable typed as a
// func, or set to a function literal or to a function by name.
func funcVars(repo *Repo, dir string, exported bool) map[string]bool {
	key := dir + " " + strconv.FormatBool(exported)
	if held, ok := repo.funcVars[key]; ok {
		return held
	}
	if repo.funcVars == nil {
		repo.funcVars = map[string]map[string]bool{}
	}
	out := map[string]bool{}
	repo.funcVars[key] = out
	for _, q := range repo.Paths {
		if path.Dir(q) != dir || path.Ext(q) != ".go" || strings.HasSuffix(q, "_test.go") {
			continue
		}
		t, ok, err := repo.Read(q)
		if err != nil || !ok {
			continue
		}
		f, err := parser.ParseFile(token.NewFileSet(), q, t, parser.SkipObjectResolution)
		if err != nil {
			continue
		}
		for _, d := range f.Decls {
			g, ok := d.(*ast.GenDecl)
			if !ok || g.Tok != token.VAR {
				continue
			}
			for _, s := range g.Specs {
				vs := s.(*ast.ValueSpec)
				for i, name := range vs.Names {
					if exported && !name.IsExported() {
						continue
					}
					var value ast.Expr
					if i < len(vs.Values) {
						value = vs.Values[i]
					}
					if isFuncValue(vs.Type, value) {
						out[name.Name] = true
					}
				}
			}
		}
	}
	return out
}

// isFuncValue says whether a variable of this type and value holds a
// function, as far as the syntax tells.
func isFuncValue(typ, value ast.Expr) bool {
	if _, ok := typ.(*ast.FuncType); ok {
		return true
	}
	if typ != nil {
		return false
	}
	switch v := value.(type) {
	case *ast.FuncLit:
		return true
	case *ast.SelectorExpr:
		// os.Executable, a function by name; a call would be a CallExpr.
		return true
	case *ast.Ident:
		return v.Name != "true" && v.Name != "false" && v.Name != "nil" && v.Name != "iota"
	}
	return false
}

// declaredIn answers every name the function declares: its parameters and
// results, and the variables and functions declared anywhere in its body.
// An assignment to one of them is to a local, not to the package.
func declaredIn(fn *ast.FuncDecl) map[string]bool {
	out := map[string]bool{}
	fields := func(l *ast.FieldList) {
		if l == nil {
			return
		}
		for _, f := range l.List {
			for _, n := range f.Names {
				out[n.Name] = true
			}
		}
	}
	if fn.Recv != nil {
		fields(fn.Recv)
	}
	ast.Inspect(fn, func(n ast.Node) bool {
		switch n := n.(type) {
		case *ast.FuncType:
			fields(n.Params)
			fields(n.Results)
		case *ast.AssignStmt:
			if n.Tok == token.DEFINE {
				for _, l := range n.Lhs {
					if id, ok := l.(*ast.Ident); ok {
						out[id.Name] = true
					}
				}
			}
		case *ast.RangeStmt:
			if n.Tok == token.DEFINE {
				for _, e := range []ast.Expr{n.Key, n.Value} {
					if id, ok := e.(*ast.Ident); ok {
						out[id.Name] = true
					}
				}
			}
		case *ast.ValueSpec:
			for _, id := range n.Names {
				out[id.Name] = true
			}
		}
		return true
	})
	return out
}

// modulePath answers the module go.mod names; "" where there is none.
func modulePath(repo *Repo) string {
	t, ok, err := repo.Read("go.mod")
	if err != nil || !ok {
		return ""
	}
	for _, line := range strings.Split(string(t), "\n") {
		if m, ok := strings.CutPrefix(strings.TrimSpace(line), "module "); ok {
			return strings.Trim(strings.TrimSpace(m), `"`)
		}
	}
	return ""
}
