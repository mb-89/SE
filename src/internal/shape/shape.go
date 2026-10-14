// Package shape finds the facts an overhaul's pruning and code-shape judgment
// reads (spec/overhaul.md): what nothing reaches in production, duplicates
// and near-duplicates, sizes, one-user abstractions, unused se surfaces, code
// serving a state that may no longer occur, the scripts, the files untouched
// longest, the longest functions, files and parameter lists, the switches on
// a kind, and how many files a change touches. Read reads the checkout; Find
// is pure.
package shape

import (
	"go/ast"
	"go/parser"
	"go/scanner"
	"go/token"
	"go/types"
	"hash/fnv"
	"maps"
	"path"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Input is what Find works on.
type Input struct {
	// Files are the Go files and Scripts the scripts, by their path in the
	// checkout; Module is the Go module's path.
	Files, Scripts map[string][]byte
	Module         string
	// Deadcode is what `deadcode ./...` printed in src.
	Deadcode string
	// Tracked are the files git tracks; Log is git log in Read's format.
	Tracked []string
	Log     string
	// Commands are se's commands with their flags; Ran the se command lines
	// that ran: the session logs' and those the comments se wrote stand for.
	// Those that ran before Since (zero: the whole history) do not count.
	Commands []Surface
	Ran      []Ran
	Since    time.Time
	// ReadBy is when the last retro's window ended: a script added before
	// then, that retro has read. Zero where no retro reported.
	ReadBy time.Time
}

// Surface is one se command and its flags.
type Surface struct {
	Name  string
	Flags []string
}

// Place is a piece of code: where it is and what it is.
type Place struct{ At, What string }

// Pair is two functions alike: Alike percent of their shape is the same.
type Pair struct {
	A, B  Place
	Alike int
}

// Size is the lines of code and of test code of a package or a module, and
// its share of all the code, in percent.
type Size struct {
	Name             string
	Lines, TestLines int
	Share            int
}

// Measure is a piece of code and how big it is by one measure.
type Measure struct {
	Place
	N int
}

// Script is a file in src/scripts: why it was needed, when it came, whether
// the last retro has read it, and the se commands it names.
type Script struct {
	Path, Why string
	Added     time.Time
	Read      bool
	Names     []string
}

// Touched is a tracked file and its last change.
type Touched struct {
	Path string
	Last time.Time
}

// Change is one change on main and how many files it touched.
type Change struct {
	SHA, Subject string
	Files        int
}

// Facts are what Find found, longest or most alike first.
type Facts struct {
	Unreachable []Place
	Duplicates  []Pair
	Near        []Pair
	Packages    []Size
	Modules     []Size
	Lines       int
	TestLines   int
	Libraries   []Place
	Registries  []Place
	Interfaces  []Place
	// Unused are the commands, and the flags of those that ran, that no line
	// ran; Counted says how many commands ran: none, and the fact is dropped.
	Unused     []string
	Counted    int
	Since      time.Time
	Legacy     []Place
	Scripts    []Script
	Untouched  []Touched
	LongFuncs  []Measure
	LongFiles  []Measure
	LongParams []Measure
	Switches   []Measure
	// Changes counts the changes on main the files-touched figures read.
	Changes, MedianFiles, MaxFiles int
	Widest                         []Change
}

// The thresholds: a duplicate has at least minTokens tokens; near-duplicates
// share nearAlike percent of their shingles of shingle tokens, a shingle in
// more than common functions being an idiom, not a copy; a switch on a kind
// has kindArms arms; the files-touched figures read the last recent changes
// where no window starts.
const (
	minTokens = 40
	shingle   = 8
	nearAlike = 75
	common    = 8
	kindArms  = 3
	recent    = 100
)

// legacy is a comment that says code serves an old state.
var legacy = regexp.MustCompile(`(?i)\b(from before|before \w+ stopped|legacy|deprecated|no longer|kept for|for old)\b`)

// fn is one production function as the duplicate search sees it.
type fn struct {
	Place
	raw    uint64
	shapes []uint64
}

// scan is what one pass over the Go files gathers.
type scan struct {
	in        Input
	fset      *token.FileSet
	f         Facts
	pkgLines  map[string]*Size
	mains     map[string]bool
	importers map[string]map[string]bool
	tested    map[string]bool
	methods   map[string]map[string]bool
	typeAt    map[string]string
	ifaces    []iface
	registers map[string]string
	calls     map[string]int
	fns       []fn
}

type iface struct {
	Place
	methods []string
}

// Find finds the facts in in.
func Find(in Input) Facts {
	s := &scan{
		in: in, fset: token.NewFileSet(), pkgLines: map[string]*Size{}, mains: map[string]bool{},
		importers: map[string]map[string]bool{}, tested: map[string]bool{}, methods: map[string]map[string]bool{},
		typeAt: map[string]string{}, registers: map[string]string{}, calls: map[string]int{},
	}
	s.f.Since = in.Since
	for _, p := range slices.Sorted(maps.Keys(in.Files)) {
		s.file(p, in.Files[p])
	}
	s.unreachable()
	s.duplicates()
	s.sizes()
	s.oneUser()
	s.unused()
	s.history()
	byN := func(ms []Measure) {
		sort.SliceStable(ms, func(a, b int) bool { return ms[a].N > ms[b].N })
	}
	byN(s.f.LongFuncs)
	byN(s.f.LongFiles)
	byN(s.f.LongParams)
	byN(s.f.Switches)
	return s.f
}

func (s *scan) at(pos token.Pos) string {
	p := s.fset.Position(pos)
	return p.Filename + ":" + strconv.Itoa(p.Line)
}

// file reads one Go file into the scan.
func (s *scan) file(p string, data []byte) {
	f, err := parser.ParseFile(s.fset, p, data, parser.ParseComments)
	if err != nil {
		return
	}
	dir, test := path.Dir(p), strings.HasSuffix(p, "_test.go")
	size := s.pkgLines[dir]
	if size == nil {
		size = &Size{Name: dir}
		s.pkgLines[dir] = size
	}
	lines := 0
	for _, l := range strings.Split(string(data), "\n") {
		if strings.TrimSpace(l) != "" {
			lines++
		}
	}
	if test {
		size.TestLines += lines
	} else {
		size.Lines += lines
		s.f.LongFiles = append(s.f.LongFiles, Measure{Place{p, path.Base(p)}, strings.Count(string(data), "\n")})
	}
	if f.Name.Name == "main" {
		s.mains[dir] = true
	}
	alias := map[string]string{}
	for _, imp := range f.Imports {
		target, err := strconv.Unquote(imp.Path.Value)
		if err != nil || !strings.HasPrefix(target, s.in.Module+"/") {
			continue
		}
		at := "src/" + strings.TrimPrefix(target, s.in.Module+"/")
		name := path.Base(at)
		if imp.Name != nil {
			name = imp.Name.Name
		}
		alias[name] = at
		if test {
			s.tested[at] = true
			continue
		}
		if s.importers[at] == nil {
			s.importers[at] = map[string]bool{}
		}
		s.importers[at][dir] = true
	}
	for _, d := range f.Decls {
		s.decl(p, dir, test, data, d)
	}
	if test {
		return
	}
	for _, g := range f.Comments {
		for k, line := range strings.Split(g.Text(), "\n") {
			if legacy.MatchString(line) {
				s.f.Legacy = append(s.f.Legacy, Place{p + ":" + strconv.Itoa(s.fset.Position(g.Pos()).Line+k), strings.TrimSpace(line)})
			}
		}
	}
	ast.Inspect(f, func(n ast.Node) bool {
		switch n := n.(type) {
		case *ast.CallExpr:
			switch fun := n.Fun.(type) {
			case *ast.Ident:
				s.calls[dir+"."+fun.Name]++
			case *ast.SelectorExpr:
				if x, ok := fun.X.(*ast.Ident); ok && alias[x.Name] != "" {
					s.calls[alias[x.Name]+"."+fun.Sel.Name]++
				}
			}
		case *ast.SwitchStmt:
			if n.Tag != nil {
				s.kindSwitch(n.Pos(), "switch on "+types.ExprString(n.Tag), n.Body)
			}
		case *ast.TypeSwitchStmt:
			s.kindSwitch(n.Pos(), "switch on a type", n.Body)
		}
		return true
	})
}

// kindSwitch records a switch with kindArms arms or more, default left out.
func (s *scan) kindSwitch(pos token.Pos, what string, body *ast.BlockStmt) {
	arms := 0
	for _, c := range body.List {
		if cc, ok := c.(*ast.CaseClause); ok && cc.List != nil {
			arms++
		}
	}
	if arms >= kindArms {
		s.f.Switches = append(s.f.Switches, Measure{Place{s.at(pos), what}, arms})
	}
}

// receiver is the name of a method's type.
func receiver(e ast.Expr) string {
	switch t := e.(type) {
	case *ast.StarExpr:
		return receiver(t.X)
	case *ast.IndexExpr:
		return receiver(t.X)
	case *ast.IndexListExpr:
		return receiver(t.X)
	case *ast.Ident:
		return t.Name
	}
	return ""
}

func (s *scan) decl(p, dir string, test bool, data []byte, d ast.Decl) {
	switch d := d.(type) {
	case *ast.GenDecl:
		for _, spec := range d.Specs {
			ts, ok := spec.(*ast.TypeSpec)
			if !ok {
				continue
			}
			s.typeAt[dir+"."+ts.Name.Name] = p
			if it, ok := ts.Type.(*ast.InterfaceType); ok && !test {
				s.iface(ts, it)
			}
		}
	case *ast.FuncDecl:
		name := d.Name.Name
		if d.Recv != nil && len(d.Recv.List) == 1 {
			t := receiver(d.Recv.List[0].Type)
			key := dir + "." + t
			if s.methods[key] == nil {
				s.methods[key] = map[string]bool{}
			}
			s.methods[key][name] = true
			if _, ok := s.typeAt[key]; !ok || test {
				s.typeAt[key] = p
			}
			name = t + "." + name
		} else if !test && strings.HasPrefix(strings.ToLower(name), "register") && d.Type.Params.NumFields() == 1 {
			s.registers[dir+"."+name] = s.at(d.Pos())
		}
		if test || d.Body == nil {
			return
		}
		place := Place{s.at(d.Pos()), name}
		start, end := s.fset.Position(d.Pos()), s.fset.Position(d.End())
		s.f.LongFuncs = append(s.f.LongFuncs, Measure{place, end.Line - start.Line + 1})
		s.f.LongParams = append(s.f.LongParams, Measure{place, d.Type.Params.NumFields()})
		s.tokens(place, data[s.fset.Position(d.Body.Pos()).Offset:end.Offset])
	}
}

// iface records an interface whose methods are all its own.
func (s *scan) iface(ts *ast.TypeSpec, it *ast.InterfaceType) {
	var names []string
	for _, m := range it.Methods.List {
		if len(m.Names) == 0 {
			return
		}
		for _, n := range m.Names {
			names = append(names, n.Name)
		}
	}
	if len(names) > 0 {
		s.ifaces = append(s.ifaces, iface{Place{s.at(ts.Pos()), ts.Name.Name}, names})
	}
}

// tokens records a function body's token stream as it is, and its shape:
// every name and literal made the same.
func (s *scan) tokens(place Place, body []byte) {
	var sc scanner.Scanner
	sc.Init(s.fset.AddFile("", -1, len(body)), body, nil, 0)
	var raw, shape []string
	for {
		_, tok, lit := sc.Scan()
		if tok == token.EOF {
			break
		}
		switch {
		case tok == token.IDENT:
			raw, shape = append(raw, lit), append(shape, "i")
		case tok.IsLiteral():
			raw, shape = append(raw, lit), append(shape, "l")
		default:
			raw, shape = append(raw, tok.String()), append(shape, tok.String())
		}
	}
	if len(raw) < minTokens {
		return
	}
	g := fn{Place: place, raw: hash(raw)}
	seen := map[uint64]bool{}
	for k := 0; k+shingle <= len(shape); k++ {
		h := hash(shape[k : k+shingle])
		if !seen[h] {
			seen[h] = true
			g.shapes = append(g.shapes, h)
		}
	}
	s.fns = append(s.fns, g)
}

func hash(words []string) uint64 {
	h := fnv.New64a()
	for _, w := range words {
		_, _ = h.Write([]byte(w))
		_, _ = h.Write([]byte{0})
	}
	return h.Sum64()
}

// duplicates pairs the functions with the same body, and the near-duplicates:
// those whose shapes share nearAlike percent of their shingles.
func (s *scan) duplicates() {
	first := map[uint64]int{}
	same := map[[2]int]bool{}
	for k, g := range s.fns {
		if j, ok := first[g.raw]; ok {
			s.f.Duplicates = append(s.f.Duplicates, Pair{s.fns[j].Place, g.Place, 100})
			same[[2]int{j, k}] = true
			continue
		}
		first[g.raw] = k
	}
	holders := map[uint64][]int{}
	for k, g := range s.fns {
		for _, h := range g.shapes {
			holders[h] = append(holders[h], k)
		}
	}
	shared := map[[2]int]int{}
	for _, ks := range holders {
		if len(ks) > common {
			continue
		}
		for a := 0; a < len(ks); a++ {
			for b := a + 1; b < len(ks); b++ {
				shared[[2]int{ks[a], ks[b]}]++
			}
		}
	}
	for pair, n := range shared {
		a, b := s.fns[pair[0]], s.fns[pair[1]]
		alike := 100 * n / (len(a.shapes) + len(b.shapes) - n)
		if alike >= nearAlike && !same[pair] {
			s.f.Near = append(s.f.Near, Pair{a.Place, b.Place, alike})
		}
	}
	sort.Slice(s.f.Near, func(x, y int) bool {
		if s.f.Near[x].Alike != s.f.Near[y].Alike {
			return s.f.Near[x].Alike > s.f.Near[y].Alike
		}
		return s.f.Near[x].A.At < s.f.Near[y].A.At
	})
}

// testOnly says a package is a test helper: tests import it, nothing else does.
func (s *scan) testOnly(dir string) bool { return s.tested[dir] && len(s.importers[dir]) == 0 }

// unreachable reads what deadcode found unreachable from the main packages,
// the fakes and the test helpers left out: code only tests reach.
func (s *scan) unreachable() {
	for _, line := range strings.Split(s.in.Deadcode, "\n") {
		where, what, ok := strings.Cut(line, ": unreachable func: ")
		if !ok {
			continue
		}
		parts := strings.Split(where, ":")
		file := "src/" + parts[0]
		if path.Base(file) == "fake.go" || strings.Contains(what, "Fake") || s.testOnly(path.Dir(file)) {
			continue
		}
		at := file
		if len(parts) > 1 {
			at += ":" + parts[1]
		}
		s.f.Unreachable = append(s.f.Unreachable, Place{at, what})
	}
}

// module is the module a package belongs to: src/cmd/se, src/internal/io.
func module(dir string) string {
	parts := strings.Split(dir, "/")
	if len(parts) > 3 {
		parts = parts[:3]
	}
	return strings.Join(parts, "/")
}

func (s *scan) sizes() {
	mods := map[string]*Size{}
	for _, dir := range slices.Sorted(maps.Keys(s.pkgLines)) {
		p := s.pkgLines[dir]
		s.f.Lines += p.Lines
		s.f.TestLines += p.TestLines
		m := mods[module(dir)]
		if m == nil {
			m = &Size{Name: module(dir)}
			mods[m.Name] = m
		}
		m.Lines += p.Lines
		m.TestLines += p.TestLines
	}
	share := func(all map[string]*Size) []Size {
		var out []Size
		for _, name := range slices.Sorted(maps.Keys(all)) {
			z := *all[name]
			if s.f.Lines > 0 {
				z.Share = (100*z.Lines + s.f.Lines/2) / s.f.Lines
			}
			out = append(out, z)
		}
		sort.SliceStable(out, func(a, b int) bool { return out[a].Lines > out[b].Lines })
		return out
	}
	s.f.Packages, s.f.Modules = share(s.pkgLines), share(mods)
}

// oneUser finds the abstractions with one user: a library one other module
// imports, a program left out (internal packages serving the program are the
// layout, not a smell), a registry with one entry, an interface with one
// implementation and no fake.
func (s *scan) oneUser() {
	for _, dir := range slices.Sorted(maps.Keys(s.importers)) {
		users := map[string]bool{}
		for from := range s.importers[dir] {
			if module(from) != module(dir) && !s.mains[from] {
				users[module(from)] = true
			}
		}
		if len(users) == 1 && !s.mains[dir] {
			s.f.Libraries = append(s.f.Libraries, Place{dir, "imported only by " + slices.Sorted(maps.Keys(users))[0]})
		}
	}
	for _, key := range slices.Sorted(maps.Keys(s.registers)) {
		if s.calls[key] <= 1 {
			s.f.Registries = append(s.f.Registries, Place{s.registers[key], key[strings.LastIndex(key, ".")+1:] + " has " + strconv.Itoa(s.calls[key]) + " entry"})
		}
	}
	for _, i := range s.ifaces {
		var real, fakes []string
		for _, key := range slices.Sorted(maps.Keys(s.methods)) {
			if !covers(s.methods[key], i.methods) {
				continue
			}
			file := s.typeAt[key]
			if strings.HasSuffix(file, "_test.go") || path.Base(file) == "fake.go" || strings.Contains(strings.ToLower(key), "fake") {
				fakes = append(fakes, key)
			} else {
				real = append(real, key)
			}
		}
		if len(real) == 1 && len(fakes) == 0 {
			s.f.Interfaces = append(s.f.Interfaces, Place{i.At, i.What + ", implemented only by " + path.Base(real[0])})
		}
	}
}

func covers(have map[string]bool, want []string) bool {
	for _, m := range want {
		if !have[m] {
			return false
		}
	}
	return true
}

// unused lists the se commands that no line run since the window started
// names, and the flags of those that ran that none gave.
func (s *scan) unused() {
	var lines []string
	for _, r := range s.in.Ran {
		if r.At.IsZero() || !r.At.Before(s.in.Since) {
			lines = append(lines, r.Line)
		}
	}
	ran := used(lines, s.in.Commands)
	if s.f.Counted = len(ran); s.f.Counted == 0 {
		return
	}
	for _, c := range s.in.Commands {
		flags, ok := ran[c.Name]
		if !ok {
			s.f.Unused = append(s.f.Unused, "se "+c.Name)
			continue
		}
		for _, flag := range c.Flags {
			if !flags[flag] {
				s.f.Unused = append(s.f.Unused, "se "+c.Name+" --"+flag)
			}
		}
	}
}
