package rules

import (
	"bytes"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// An I/O module is a door: its folder under IODir declares, in DoorFile,
// the resource it guards and what going around it looks like. Every folder
// there holding a file is a door, found by registration; no list names them.
const (
	IODir    = "src/internal/io"
	DoorFile = "owns.yaml"
	// Marker passes the one line it stands on, with the reason after it:
	// the marker, " - ", and why the line may go around the door.
	Marker = "se: around-the-door"
)

// Door is one I/O module's declaration.
type Door struct {
	// At is its folder.
	At string `yaml:"-"`
	// Guards says the resource it guards, in one line: what it is, a colon,
	// and what of it. The part before the colon names it in a finding.
	Guards string `yaml:"guards"`
	// Go are the Go imports, such as os/exec, and package members, such as
	// time.Now, that reach the resource. An import covers its subpackages.
	Go []string `yaml:"go"`
	// Commands are the words that reach the resource from a shell line or
	// from text an agent is told to run, such as gh; a word ending in * is
	// any word it starts.
	Commands []string `yaml:"commands"`
}

// Resource names what the door guards: its Guards up to the colon.
func (d *Door) Resource() string {
	r, _, _ := strings.Cut(d.Guards, ":")
	return strings.TrimSpace(r)
}

// doors is every door of the checkout, read once per run.
type doors struct {
	// faults are what is wrong with a declaration, by its path.
	faults map[string][]Finding
	// bare names, by the first file of its folder, a folder that declares nothing.
	bare    map[string]string
	imports map[string]*Door
	members map[string]map[string]*Door
	words   []doorWord
}

// doorWord is one of a door's commands, as the expression that finds it.
type doorWord struct {
	name string
	re   *regexp.Regexp
	door *Door
}

var (
	goImport  = regexp.MustCompile(`^[a-z][a-z0-9_.-]*(/[A-Za-z0-9_.-]+)*$`)
	goMember  = regexp.MustCompile(`^[A-Z][A-Za-z0-9_]*$`)
	aWord     = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9_.:/-]*\*?$`)
	markedAt  = regexp.MustCompile(regexp.QuoteMeta(Marker) + `(?:\s+-\s+(\S.*))?`)
	wordChars = `A-Za-z0-9_-`
)

// doorsOf answers the checkout's doors, reading each declaration once.
func doorsOf(repo *Repo) *doors {
	if repo.doors != nil {
		return repo.doors
	}
	ds := &doors{faults: map[string][]Finding{}, bare: map[string]string{}, imports: map[string]*Door{}, members: map[string]map[string]*Door{}}
	repo.doors = ds
	first := map[string]string{}
	for _, p := range repo.Paths {
		if at := doorOf(p); at != "" && (first[at] == "" || p < first[at]) {
			first[at] = p
		}
	}
	folders := make([]string, 0, len(first))
	for at := range first {
		folders = append(folders, at)
	}
	sort.Strings(folders)
	owner := map[string]*Door{}
	for _, at := range folders {
		decl := at + "/" + DoorFile
		text, ok, err := repo.Read(decl)
		if err != nil || !ok {
			ds.bare[first[at]] = at
			continue
		}
		fault := func(msg string, args ...any) {
			ds.faults[decl] = append(ds.faults[decl], Finding{Path: decl, Line: 1, Rule: "io-module", Message: fmt.Sprintf(msg, args...)})
		}
		d := &Door{At: at}
		dec := yaml.NewDecoder(bytes.NewReader(text))
		dec.KnownFields(true)
		if err := dec.Decode(d); err != nil {
			fault("%s reads as no declaration: %v; it holds guards, go and commands", DoorFile, err)
			continue
		}
		if d.Resource() == "" {
			fault("it says no resource it guards: write guards: \"<what>: <what of it>\"")
		}
		claim := func(key, name string) bool {
			if o := owner[key]; o != nil {
				fault("%s is %s's already: one door owns a name", name, o.At)
				return false
			}
			owner[key] = d
			return true
		}
		for _, name := range d.Go {
			pkg, member := splitGo(name)
			switch {
			case !goImport.MatchString(pkg) || (member != "" && !goMember.MatchString(member)):
				fault("%s reads as no Go import or package member, such as os/exec or time.Now", name)
			case !claim("go "+name, name):
			case member == "":
				ds.imports[pkg] = d
			default:
				if ds.members[pkg] == nil {
					ds.members[pkg] = map[string]*Door{}
				}
				ds.members[pkg][member] = d
			}
		}
		for _, name := range d.Commands {
			if !aWord.MatchString(name) {
				fault("%s reads as no command word, such as gh or mcp__github__*", name)
				continue
			}
			if claim("command "+name, name) {
				ds.words = append(ds.words, doorWord{name: name, re: wordRe(name), door: d})
			}
		}
	}
	return ds
}

// doorOf answers the door folder a path stands in, or "" outside every door.
func doorOf(p string) string {
	rest, ok := strings.CutPrefix(p, IODir+"/")
	if !ok {
		return ""
	}
	name, _, deeper := strings.Cut(rest, "/")
	if !deeper {
		return ""
	}
	return IODir + "/" + name
}

// splitGo answers a Go name's package path and its member, "" for an import.
func splitGo(name string) (pkg, member string) {
	if i := strings.LastIndex(name, "."); i > strings.LastIndex(name, "/") {
		if m := name[i+1:]; goMember.MatchString(m) {
			return name[:i], m
		}
	}
	return name, ""
}

// wordRe finds a command as a word: not inside a longer one, so ghost is no gh.
func wordRe(name string) *regexp.Regexp {
	body := regexp.QuoteMeta(strings.TrimSuffix(name, "*"))
	if strings.HasSuffix(name, "*") {
		body += `[A-Za-z0-9_]*`
	}
	return regexp.MustCompile(`(?:^|[^` + wordChars + `])(` + body + `)(?:$|[^` + wordChars + `])`)
}

// importer answers the door owning an import path: itself or a parent's.
func (ds *doors) importer(ip string) *Door {
	for p := ip; ; p = path.Dir(p) {
		if d := ds.imports[p]; d != nil {
			return d
		}
		if !strings.Contains(p, "/") {
			return nil
		}
	}
}

// membersOf answers the members of the package at pkg that doors own, in order.
func (ds *doors) membersOf(pkg string) []string {
	var out []string
	for m := range ds.members[pkg] {
		out = append(out, m)
	}
	sort.Strings(out)
	return out
}

// walk is one way a line goes around a door: what it names, as the door
// declares it and as the line says it.
type walk struct {
	what, said string
	line       int
	door       *Door
}

// marks answers each line holding the marker, with its reason ("" for none).
type marks map[int]string

// goWalks answers every way the Go file goes around a door, each what once
// per line, and the lines it marks in its comments. A file that does not
// parse goes around nothing the rule can tell.
func (ds *doors) goWalks(p string, text []byte) ([]walk, marks) {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution|parser.ParseComments)
	if err != nil {
		return nil, nil
	}
	var out []walk
	note := func(what string, d *Door, pos token.Pos) {
		out = append(out, walk{what: what, said: what, line: fset.Position(pos).Line, door: d})
	}
	local := map[string]string{} // the name a package goes by in the file, to its path
	execName := ""               // the name os/exec goes by in the file
	for _, im := range f.Imports {
		ip, _ := strconv.Unquote(im.Path.Value)
		name := path.Base(ip)
		if im.Name != nil {
			name = im.Name.Name
		}
		if d := ds.importer(ip); d != nil {
			note(ip, d, im.Pos())
		}
		if ip == "os/exec" {
			execName = name
		}
		if ds.members[ip] != nil {
			local[name] = ip
		}
	}
	ast.Inspect(f, func(n ast.Node) bool {
		if call, ok := n.(*ast.CallExpr); ok && execName != "" {
			if prog, ok := started(call, execName); ok {
				for _, w := range ds.words {
					if w.re.MatchString(prog) {
						note(w.name, w.door, call.Pos())
					}
				}
			}
		}
		sel, ok := n.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		id, ok := sel.X.(*ast.Ident)
		if !ok {
			return true
		}
		if d := ds.members[local[id.Name]][sel.Sel.Name]; d != nil {
			note(local[id.Name]+"."+sel.Sel.Name, d, sel.Pos())
		}
		return true
	})
	m := marks{}
	for _, g := range f.Comments {
		for _, c := range g.List {
			if hit := markedAt.FindStringSubmatch(c.Text); hit != nil {
				m[fset.Position(c.Pos()).Line] = strings.TrimSpace(hit[1])
			}
		}
	}
	return out, m
}

// started answers the program a call of exec.Command or exec.CommandContext
// names, by the name os/exec goes by, where it names one.
func started(call *ast.CallExpr, execName string) (string, bool) {
	sel, ok := call.Fun.(*ast.SelectorExpr)
	if !ok {
		return "", false
	}
	if id, ok := sel.X.(*ast.Ident); !ok || id.Name != execName {
		return "", false
	}
	at, ok := map[string]int{"Command": 0, "CommandContext": 1}[sel.Sel.Name]
	if !ok || len(call.Args) <= at {
		return "", false
	}
	lit, ok := call.Args[at].(*ast.BasicLit)
	if !ok || lit.Kind != token.STRING {
		return "", false
	}
	name, err := strconv.Unquote(lit.Value)
	return name, err == nil
}

// textWalks answers every command of a door a line of the text names, and the
// lines it marks.
func (ds *doors) textWalks(text []byte) ([]walk, marks) {
	var out []walk
	m := marks{}
	for i, line := range strings.Split(string(text), "\n") {
		for _, w := range ds.words {
			if hit := w.re.FindStringSubmatch(line); hit != nil {
				out = append(out, walk{what: w.name, said: hit[1], line: i + 1, door: w.door})
			}
		}
		if hit := markedAt.FindStringSubmatch(line); hit != nil {
			m[i+1] = strings.TrimSpace(hit[1])
		}
	}
	return out, m
}
