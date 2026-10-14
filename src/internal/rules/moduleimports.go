package rules

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"sort"
	"strconv"
	"strings"
)

// The layout spec/index.md sets: the core, the modules and the libraries.
const (
	modulesDir   = "src/modules"
	libDir       = "src/lib"
	indexPackage = "github.com/mb-89/SE/src/index"
	libPackages  = "github.com/mb-89/SE/" + libDir + "/"
)

// impure is the standard library that reaches the outside: the disk, the
// processes, the network, the system and chance. A path names itself and every
// package under it.
var impure = []string{"os", "net", "syscall", "io/ioutil", "plugin", "unsafe", "crypto/rand", "math/rand", "log"}

func init() {
	register(Rule{
		Name: "module-imports",
		Doc: "a compute module under " + modulesDir + " (one without the I/O flag, index.IO()) and a library under " + libDir +
			" import the index contract, the libraries and the pure standard library only, and never read the clock",
		Applies: func(p string) bool { return goSource(p) && (under(p, modulesDir) || under(p, libDir)) },
		Check:   moduleImports,
	})
}

// goSource says whether p is a Go file that is no test.
func goSource(p string) bool { return path.Ext(p) == ".go" && !strings.HasSuffix(p, "_test.go") }

// under says whether p lies in the folder dir.
func under(p, dir string) bool { return strings.HasPrefix(p, dir+"/") }

func moduleImports(repo *Repo, p string, text []byte) []Finding {
	if under(p, modulesDir) && carriesIOFlag(repo, path.Dir(p)) {
		return nil
	}
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	what := "a compute module"
	if under(p, libDir) {
		what = "a library"
	}
	var found []Finding
	refuse := func(pos token.Pos, msg string) {
		found = append(found, Finding{Path: p, Line: fset.Position(pos).Line, Rule: "module-imports", Message: msg})
	}
	timeName := ""
	for _, im := range f.Imports {
		ip, _ := strconv.Unquote(im.Path.Value)
		if ip == "time" {
			timeName = "time"
			if im.Name != nil {
				timeName = im.Name.Name
			}
		}
		if !pureImport(ip) {
			refuse(im.Pos(), fmt.Sprintf("%s imports %s: it may import the index contract (src/index), the libraries (%s) and the pure standard library only (spec/index.md)", what, ip, libDir))
		}
	}
	if timeName == "" {
		return found
	}
	ast.Inspect(f, func(n ast.Node) bool {
		sel, ok := n.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		if id, ok := sel.X.(*ast.Ident); ok && id.Name == timeName {
			for _, name := range doorsOf(repo).membersOf("time") {
				if sel.Sel.Name == name {
					refuse(sel.Pos(), fmt.Sprintf("%s reads the clock or waits through time.%s: only the clock's I/O module does (spec/index.md)", what, name))
				}
			}
		}
		return true
	})
	return found
}

// pureImport says whether a compute module or a library may import ip.
func pureImport(ip string) bool {
	if ip == indexPackage || strings.HasPrefix(ip, libPackages) {
		return true
	}
	if first, _, _ := strings.Cut(ip, "/"); strings.Contains(first, ".") {
		return false
	}
	for _, o := range impure {
		if ip == o || strings.HasPrefix(ip, o+"/") {
			return false
		}
	}
	return true
}

// carriesIOFlag says whether the package in dir declares the I/O flag: one of
// its Go files calls IO() on the index contract.
func carriesIOFlag(repo *Repo, dir string) bool {
	for _, p := range packageFiles(repo, dir) {
		text, ok, err := repo.Read(p)
		if err != nil || !ok {
			continue
		}
		f, err := parser.ParseFile(token.NewFileSet(), p, text, parser.SkipObjectResolution)
		if err != nil {
			continue
		}
		name := ""
		for _, im := range f.Imports {
			if ip, _ := strconv.Unquote(im.Path.Value); ip == indexPackage {
				name = "index"
				if im.Name != nil {
					name = im.Name.Name
				}
			}
		}
		if name == "" {
			continue
		}
		flagged := false
		ast.Inspect(f, func(n ast.Node) bool {
			call, ok := n.(*ast.CallExpr)
			if !ok {
				return !flagged
			}
			if sel, ok := call.Fun.(*ast.SelectorExpr); ok && sel.Sel.Name == "IO" {
				if id, ok := sel.X.(*ast.Ident); ok && id.Name == name {
					flagged = true
				}
			}
			return !flagged
		})
		if flagged {
			return true
		}
	}
	return false
}

// packageFiles answers the Go files of the package in dir, tests left out, sorted.
func packageFiles(repo *Repo, dir string) []string {
	var out []string
	for _, p := range repo.Paths {
		if goSource(p) && path.Dir(p) == dir {
			out = append(out, p)
		}
	}
	sort.Strings(out)
	return out
}
