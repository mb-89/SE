package rules

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"slices"
	"sort"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/modules/io/proc"
)

// ProgramsAllowlist names the places that still start a program proc.Programs
// does not list, one per line: a Go file and the program. It only shrinks.
const ProgramsAllowlist = "src/internal/rules/programs.txt"

// procPackage is the proc I/O module's import path, whose Cmd names a program.
const procPackage = "github.com/mb-89/SE/src/modules/io/proc"

func init() {
	register(Rule{
		Name: "programs",
		Doc: "no Go file starts a program but those proc.Programs lists (src/modules/io/proc), " +
			"and none but the proc I/O module calls os/exec, except as " + ProgramsAllowlist + " names; an entry there that matches nothing is refused",
		Applies: func(p string) bool {
			return p == ProgramsAllowlist || (path.Ext(p) == ".go" && !strings.HasSuffix(p, "_test.go"))
		},
		Check: programs,
	})
}

func programs(repo *Repo, p string, text []byte) []Finding {
	if p == ProgramsAllowlist {
		return staleEntries(repo, text, ProgramsAllowlist, "programs", Starts)
	}
	list, _, _ := repo.Read(ProgramsAllowlist)
	allowed := map[string]bool{}
	for _, e := range entriesOf(list) {
		allowed[e.file+" "+e.reach] = true
	}
	var found []Finding
	for _, r := range Starts(p, text) {
		if !allowed[p+" "+r.What] {
			found = append(found, Finding{Path: p, Line: r.Line, Rule: "programs", Message: startMessage(r.What)})
		}
	}
	return found
}

func startMessage(what string) string {
	if what == "os/exec" {
		return "starts a program past the proc I/O module; run it through proc, whose Programs it must be on (spec/io.md)"
	}
	return "starts " + what + ", which proc.Programs does not list: no process does what a library call can do; " +
		"reach it through its I/O module (principle 6, spec/io.md)"
}

// Starts answers every program the Go file starts that it may not, each once,
// in order: a proc.Cmd whose Name is a program proc.Programs does not list,
// and, outside the proc I/O module, an exec.Command or exec.CommandContext,
// as its program where it names one and as os/exec where it does not.
func Starts(p string, text []byte) []Reach {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	inProc := strings.HasPrefix(p, "src/modules/io/proc/")
	procName, execName := "", ""
	for _, im := range f.Imports {
		ip, _ := strconv.Unquote(im.Path.Value)
		name := path.Base(ip)
		if im.Name != nil {
			name = im.Name.Name
		}
		switch ip {
		case procPackage:
			procName = name
		case "os/exec":
			execName = name
		}
	}
	first := map[string]int{}
	note := func(what string, pos token.Pos) {
		if _, ok := first[what]; !ok {
			first[what] = fset.Position(pos).Line
		}
	}
	unlisted := func(e ast.Expr) (string, bool) {
		lit, ok := e.(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			return "", false
		}
		name, err := strconv.Unquote(lit.Value)
		return name, err == nil && !slices.Contains(proc.Programs, proc.NameOf(name))
	}
	ast.Inspect(f, func(n ast.Node) bool {
		switch n := n.(type) {
		case *ast.CompositeLit:
			if !isCmd(n.Type, procName, inProc) {
				return true
			}
			for _, el := range n.Elts {
				kv, ok := el.(*ast.KeyValueExpr)
				if id, isID := kv.Key.(*ast.Ident); ok && isID && id.Name == "Name" {
					if name, bad := unlisted(kv.Value); bad {
						note(name, kv.Value.Pos())
					}
				}
			}
		case *ast.CallExpr:
			sel, ok := n.Fun.(*ast.SelectorExpr)
			if !ok || inProc || execName == "" {
				return true
			}
			if id, ok := sel.X.(*ast.Ident); !ok || id.Name != execName {
				return true
			}
			at, ok := map[string]int{"Command": 0, "CommandContext": 1}[sel.Sel.Name]
			if !ok {
				return true
			}
			what := "os/exec"
			if len(n.Args) > at {
				if lit, ok := n.Args[at].(*ast.BasicLit); ok && lit.Kind == token.STRING {
					what, _ = strconv.Unquote(lit.Value)
				}
			}
			note(what, n.Pos())
		}
		return true
	})
	out := make([]Reach, 0, len(first))
	for what, line := range first {
		out = append(out, Reach{What: what, Line: line})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Line != out[j].Line {
			return out[i].Line < out[j].Line
		}
		return out[i].What < out[j].What
	})
	return out
}

// isCmd says whether a composite literal's type is proc's Cmd: proc.Cmd by
// the name the file imports proc under, or Cmd inside the proc package itself.
func isCmd(t ast.Expr, procName string, inProc bool) bool {
	switch t := t.(type) {
	case *ast.SelectorExpr:
		id, ok := t.X.(*ast.Ident)
		return ok && procName != "" && id.Name == procName && t.Sel.Name == "Cmd"
	case *ast.Ident:
		return inProc && t.Name == "Cmd"
	}
	return false
}
