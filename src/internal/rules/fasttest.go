package rules

import (
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"path"
	"sort"
	"strings"
)

// Serial names the tests that still break principle 8, one per line: a test
// file and what it breaks there, a test that does not run in parallel by its
// name, or a reach of the wall clock (time.Now, clock.Real). It only shrinks:
// an entry that matches nothing is refused.
const Serial = "src/internal/rules/serial.txt"

func init() {
	register(Rule{
		Name: "fast-test",
		Doc: "every Go test calls t.Parallel first, and outside src/internal/io no test file reads the wall clock, " +
			"sleeps or waits through time, or takes clock.Real, except as " + Serial + " names; an entry there that matches nothing is refused",
		Applies: func(p string) bool { return p == Serial || strings.HasSuffix(p, "_test.go") },
		Check:   fastTest,
		Fix:     parallelize,
	})
}

func fastTest(repo *Repo, p string, text []byte) []Finding {
	if p == Serial {
		return staleSlow(repo, text)
	}
	allowed := serialOf(repo)
	var found []Finding
	for _, s := range Slows(p, text, wallsOf(repo)) {
		if !allowed[p+" "+s.What] {
			found = append(found, Finding{Path: p, Line: s.Line, Rule: "fast-test", Message: s.Message()})
		}
	}
	return found
}

// serialOf answers the entries of Serial, each "file reach".
func serialOf(repo *Repo) map[string]bool {
	list, _, _ := repo.Read(Serial)
	allowed := map[string]bool{}
	for _, e := range entriesOf(list) {
		allowed[e.file+" "+e.reach] = true
	}
	return allowed
}

// parallelize makes t.Parallel() the first statement of every test in the
// file that lacks it and Serial does not name, moving a later t.Parallel()
// of the test's body up rather than calling it twice. A test whose *testing.T
// has no name is left to a person, as is a file that does not parse.
func parallelize(repo *Repo, p string, text []byte) ([]byte, bool) {
	if p == Serial {
		return text, false
	}
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.ParseComments|parser.SkipObjectResolution)
	if err != nil {
		return text, false
	}
	allowed := serialOf(repo)
	type edit struct {
		at, end int
		with    string
	}
	var edits []edit
	for _, d := range f.Decls {
		fn, ok := d.(*ast.FuncDecl)
		if !ok || !isTest(fn) || fn.Body == nil || parallelFirst(fn) || allowed[p+" "+fn.Name.Name] {
			continue
		}
		names := fn.Type.Params.List[0].Names
		if len(names) == 0 || names[0].Name == "_" {
			continue
		}
		t := names[0].Name
		for i, st := range fn.Body.List {
			if i > 0 && isParallel(st, t) {
				at, end := fset.Position(st.Pos()).Offset, fset.Position(st.End()).Offset
				edits = append(edits, edit{lineStart(text, at), lineEnd(text, end), ""})
			}
		}
		at := fset.Position(fn.Body.Lbrace).Offset + 1
		with := "\n\t" + t + ".Parallel()"
		if at >= len(text) || text[at] != '\n' {
			with += "\n"
		}
		edits = append(edits, edit{at, at, with})
	}
	if len(edits) == 0 {
		return text, false
	}
	sort.Slice(edits, func(i, j int) bool { return edits[i].at > edits[j].at })
	out := append([]byte(nil), text...)
	for _, e := range edits {
		out = append(out[:e.at], append([]byte(e.with), out[e.end:]...)...)
	}
	formatted, err := format.Source(out)
	if err != nil {
		return text, false
	}
	return formatted, true
}

// lineStart is where the line holding at begins, when only blanks stand
// before at on it; otherwise at.
func lineStart(text []byte, at int) int {
	i := at
	for i > 0 && (text[i-1] == ' ' || text[i-1] == '\t') {
		i--
	}
	if i == 0 || text[i-1] == '\n' {
		return i
	}
	return at
}

// lineEnd is past the newline that ends the line holding end, when only
// blanks follow end on it; otherwise end.
func lineEnd(text []byte, end int) int {
	i := end
	for i < len(text) && (text[i] == ' ' || text[i] == '\t' || text[i] == '\r') {
		i++
	}
	if i < len(text) && text[i] == '\n' {
		return i + 1
	}
	return end
}

// staleSlow refuses an entry of Serial that is malformed, named twice, or
// matches nothing in the file it names.
func staleSlow(repo *Repo, text []byte) []Finding {
	var found []Finding
	seen := map[string]bool{}
	for _, e := range entriesOf(text) {
		refuse := func(msg string) {
			found = append(found, Finding{Path: Serial, Line: e.line, Rule: "fast-test", Message: msg})
		}
		key := e.file + " " + e.reach
		switch {
		case e.file == "" || e.reach == "":
			refuse("an entry is a test file and what it breaks, such as: src/a/a_test.go TestX")
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
		for _, s := range Slows(e.file, src, wallsOf(repo)) {
			hit = hit || s.What == e.reach
		}
		if !hit {
			refuse(fmt.Sprintf("the entry matches nothing: %s no longer breaks %s; remove it", e.file, e.reach))
		}
	}
	return found
}

// Slow is one way a test file breaks principle 8: a test, by name, that does
// not call t.Parallel first, or a reach of the wall clock, such as time.Now.
type Slow struct {
	What string
	Line int
	// Serial is set when What names a test rather than a reach.
	Serial bool
}

// Message says what the finding asks for.
func (s Slow) Message() string {
	if s.Serial {
		return s.What + " does not call t.Parallel first; every test runs in parallel (principle 8), and se rules --fix makes it the first statement"
	}
	return s.What + " reaches the wall clock in a test; hand in clock.NewFake (principle 8, spec/io.md)"
}

// wallsOf answers what reads the wall clock in a test, by package path: the
// members of time a door owns (the clock's owns.yaml), and clock.Real.
func wallsOf(repo *Repo) map[string][]string {
	return map[string][]string{"time": doorsOf(repo).membersOf("time"), clockPath: {"Real"}}
}

const clockPath = "github.com/mb-89/SE/src/internal/io/clock"

// Slows answers every way the test file breaks principle 8, each once, in
// order, walls being what reads the wall clock, by package path; a file that
// does not parse breaks nothing the rule can tell.
func Slows(p string, text []byte, walls map[string][]string) []Slow {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	var out []Slow
	for _, d := range f.Decls {
		fn, ok := d.(*ast.FuncDecl)
		if ok && isTest(fn) && !parallelFirst(fn) {
			out = append(out, Slow{What: fn.Name.Name, Line: fset.Position(fn.Pos()).Line, Serial: true})
		}
	}
	if strings.HasPrefix(p, "src/internal/io/") {
		return out
	}
	local := map[string]string{}
	for _, im := range f.Imports {
		ip := strings.Trim(im.Path.Value, `"`)
		if _, ok := walls[ip]; ok {
			name := path.Base(ip)
			if im.Name != nil {
				name = im.Name.Name
			}
			local[name] = ip
		}
	}
	seen := map[string]bool{}
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
		for _, name := range walls[ip] {
			what := path.Base(ip) + "." + name
			if sel.Sel.Name == name && !seen[what] {
				seen[what] = true
				out = append(out, Slow{What: what, Line: fset.Position(sel.Pos()).Line})
			}
		}
		return true
	})
	return out
}

// isTest says whether fn is a test go test runs: TestX(t *testing.T).
func isTest(fn *ast.FuncDecl) bool {
	name := fn.Name.Name
	if fn.Recv != nil || !strings.HasPrefix(name, "Test") || name == "TestMain" {
		return false
	}
	if rest := name[len("Test"):]; rest != "" && strings.ToLower(rest[:1]) == rest[:1] && !strings.HasPrefix(rest, "_") {
		return false
	}
	params := fn.Type.Params.List
	if len(params) != 1 || len(params[0].Names) > 1 {
		return false
	}
	star, ok := params[0].Type.(*ast.StarExpr)
	if !ok {
		return false
	}
	sel, ok := star.X.(*ast.SelectorExpr)
	return ok && sel.Sel.Name == "T"
}

// parallelFirst says whether the test's first statement is <t>.Parallel().
func parallelFirst(fn *ast.FuncDecl) bool {
	if fn.Body == nil || len(fn.Body.List) == 0 || len(fn.Type.Params.List[0].Names) == 0 {
		return false
	}
	return isParallel(fn.Body.List[0], fn.Type.Params.List[0].Names[0].Name)
}

// isParallel says whether the statement is <t>.Parallel().
func isParallel(stmt ast.Stmt, t string) bool {
	st, ok := stmt.(*ast.ExprStmt)
	if !ok {
		return false
	}
	call, ok := st.X.(*ast.CallExpr)
	if !ok || len(call.Args) != 0 {
		return false
	}
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok || sel.Sel.Name != "Parallel" {
		return false
	}
	id, ok := sel.X.(*ast.Ident)
	return ok && id.Name == t
}
