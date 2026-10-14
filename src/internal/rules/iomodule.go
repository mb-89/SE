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
// the calls of time and os, by package path.
var (
	outsideImports = []string{"os/exec", "net/http"}
	outsideCalls   = map[string][]string{
		"time": {"Now", "Sleep", "After", "Since", "Until", "Tick", "NewTicker", "NewTimer", "AfterFunc"},
		"os": {
			"Open", "OpenFile", "Create", "CreateTemp", "ReadFile", "WriteFile", "ReadDir",
			"Mkdir", "MkdirAll", "MkdirTemp", "Remove", "RemoveAll", "Rename", "Stat", "Lstat",
			"Truncate", "Chmod", "Chown", "Chtimes", "Link", "Symlink", "Readlink", "DirFS", "CopyFS",
		},
	}
)

func init() {
	register(Rule{
		Name: "io-module",
		Doc: "outside src/internal/io, no Go file imports os/exec or net/http, reads the clock, sleeps or waits through time, " +
			"or opens, reads or writes files through os, except as " + Allowlist + " names; an entry there that matches nothing is refused",
		Applies: func(p string) bool {
			return p == Allowlist || (path.Ext(p) == ".go" && !strings.HasSuffix(p, "_test.go") && !strings.HasPrefix(p, "src/internal/io/"))
		},
		Check: ioModule,
	})
}

func ioModule(repo *Repo, p string, text []byte) []Finding {
	if p == Allowlist {
		return staleEntries(repo, text)
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

// staleEntries refuses an allowlist entry that is malformed, named twice, or
// matches nothing in the file it names.
func staleEntries(repo *Repo, text []byte) []Finding {
	var found []Finding
	seen := map[string]bool{}
	for _, e := range entriesOf(text) {
		refuse := func(msg string) {
			found = append(found, Finding{Path: Allowlist, Line: e.line, Rule: "io-module", Message: msg})
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
		for _, r := range Reaches(e.file, src) {
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
	for _, im := range f.Imports {
		ip, _ := strconv.Unquote(im.Path.Value)
		for _, o := range outsideImports {
			if ip == o {
				note(ip, im.Pos())
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
