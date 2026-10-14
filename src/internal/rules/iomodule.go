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

// Allowlist names the places outside src/internal/io that still reach the
// outside directly, one per line: a Go file and what it reaches. It only
// shrinks: each I/O module removes its own entries, and an entry that matches
// nothing is refused.
const Allowlist = "src/internal/io/allowlist.txt"

// outside is what reaches the outside past an I/O module: the imports, and
// the calls of time, os and path/filepath, by package path.
var (
	outsideImports = []string{"os/exec", "net/http"}
	outsideCalls   = map[string][]string{
		"time": {"Now", "Sleep", "After", "Since", "Until", "Tick", "NewTicker", "NewTimer", "AfterFunc"},
		"os": {
			"Open", "OpenFile", "Create", "CreateTemp", "ReadFile", "WriteFile", "ReadDir",
			"Mkdir", "MkdirAll", "MkdirTemp", "Remove", "RemoveAll", "Rename", "Stat", "Lstat",
			"Truncate", "Chmod", "Chown", "Chtimes", "Link", "Symlink", "Readlink", "DirFS", "CopyFS",
		},
		"path/filepath": {"Walk", "WalkDir", "Glob"},
	}
)

func init() {
	register(Rule{
		Name: "io-module",
		Doc: "outside src/internal/io, no Go file imports os/exec or net/http, runs gh, reads the clock, sleeps or waits through time, " +
			"opens, reads or writes files through os, or walks or globs the disk through path/filepath, except as " + Allowlist + " names; an entry there that matches nothing is refused",
		Applies: func(p string) bool {
			return p == Allowlist || (path.Ext(p) == ".go" && !strings.HasSuffix(p, "_test.go") && !strings.HasPrefix(p, "src/internal/io/"))
		},
		Check: ioModule,
	})
}

func ioModule(repo *Repo, p string, text []byte) []Finding {
	if p == Allowlist {
		return staleEntries(repo, text, Allowlist, "io-module", Reaches)
	}
	list, _, _ := repo.Read(Allowlist)
	allowed := map[string]bool{}
	for _, e := range entriesOf(list) {
		allowed[e.file+" "+e.reach] = true
	}
	var found []Finding
	for _, r := range Reaches(p, text) {
		if !allowed[p+" "+r.What] {
			found = append(found, Finding{Path: p, Line: r.Line, Rule: "io-module", Message: r.What + " reaches the outside past an I/O module; go through one under src/internal/io (spec/io.md)"})
		}
	}
	return found
}

// staleEntries refuses an entry of the allowlist at list, rule's, that is
// malformed, named twice, or matches nothing reaches finds in the file it names.
func staleEntries(repo *Repo, text []byte, list, rule string, reaches func(p string, text []byte) []Reach) []Finding {
	var found []Finding
	seen := map[string]bool{}
	for _, e := range entriesOf(text) {
		refuse := func(msg string) {
			found = append(found, Finding{Path: list, Line: e.line, Rule: rule, Message: msg})
		}
		key := e.file + " " + e.reach
		switch {
		case e.file == "" || e.reach == "":
			refuse("an entry is a Go file and what it reaches, such as: src/cmd/se/x.go os/exec")
			continue
		case seen[key]:
			refuse("the entry is named twice: " + key)
			continue
		}
		seen[key] = true
		src, ok, err := repo.Read(e.file)
		if err != nil || !ok {
			refuse("the entry names no such file: " + e.file + "; remove it")
			continue
		}
		hit := false
		for _, r := range reaches(e.file, src) {
			hit = hit || r.What == e.reach
		}
		if !hit {
			refuse(fmt.Sprintf("the entry matches nothing: %s no longer reaches %s; remove it", e.file, e.reach))
		}
	}
	return found
}

type entry struct {
	line        int
	file, reach string
}

// entriesOf reads the allowlist: a line is a file and what it reaches; a
// blank line or one starting with # says nothing.
func entriesOf(text []byte) []entry {
	var out []entry
	for i, line := range strings.Split(string(text), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.Fields(line)
		e := entry{line: i + 1}
		if len(f) == 2 {
			e.file, e.reach = f[0], f[1]
		}
		out = append(out, e)
	}
	return out
}

// runsGh says whether call is exec.Command("gh", …), or its CommandContext:
// GitHub, which only its I/O module reaches.
func runsGh(call *ast.CallExpr, execName string) bool {
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok {
		return false
	}
	if id, ok := sel.X.(*ast.Ident); !ok || id.Name != execName {
		return false
	}
	at, ok := map[string]int{"Command": 0, "CommandContext": 1}[sel.Sel.Name]
	if !ok || len(call.Args) <= at {
		return false
	}
	lit, ok := call.Args[at].(*ast.BasicLit)
	if !ok {
		return false
	}
	name, err := strconv.Unquote(lit.Value)
	return err == nil && name == "gh"
}

// Reach is one way a Go file reaches the outside: an import path, such as
// os/exec, or a call, such as time.Now, and the first line it is on.
type Reach struct {
	What string
	Line int
}

// Reaches answers every way the Go file reaches the outside directly, each
// once, in order; a file that does not parse reaches nothing the rule can tell.
func Reaches(p string, text []byte) []Reach {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	first := map[string]int{}
	note := func(what string, pos token.Pos) {
		if _, ok := first[what]; !ok {
			first[what] = fset.Position(pos).Line
		}
	}
	local := map[string]string{} // the name a package goes by in the file, to its path
	execName := ""               // the name os/exec goes by in the file
	for _, im := range f.Imports {
		ip, _ := strconv.Unquote(im.Path.Value)
		for _, o := range outsideImports {
			if ip == o {
				note(ip, im.Pos())
			}
		}
		if ip == "os/exec" {
			execName = "exec"
			if im.Name != nil {
				execName = im.Name.Name
			}
		}
		if _, ok := outsideCalls[ip]; ok {
			name := path.Base(ip)
			if im.Name != nil {
				name = im.Name.Name
			}
			local[name] = ip
		}
	}
	ast.Inspect(f, func(n ast.Node) bool {
		if call, ok := n.(*ast.CallExpr); ok && execName != "" && runsGh(call, execName) {
			note("gh", call.Pos())
		}
		sel, ok := n.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		id, ok := sel.X.(*ast.Ident)
		if !ok {
			return true
		}
		ip, ok := local[id.Name]
		if !ok {
			return true
		}
		for _, name := range outsideCalls[ip] {
			if sel.Sel.Name == name {
				note(ip+"."+name, sel.Pos())
			}
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
