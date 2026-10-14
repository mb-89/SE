package issues

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// codeShown is how many of the widest PRs and the longest untouched files
// the draft lists.
const codeShown = 10

// CodeFacts are the facts on principles 2 and 3 a command can find in the
// checkout: where a fact may be written twice, a change spread wide, or code
// no longer earns its place. The overhaul judges them.
type CodeFacts struct {
	// Since is when the previous overhaul closed; zero for the whole history.
	Since time.Time `yaml:"since,omitempty"`
	// Widest are the PRs merged on main since then that touched the most files.
	Widest []WidePR `yaml:"widest"`
	// Unreached are the functions and methods under src/ whose name nothing
	// else names, tests included.
	Unreached []Unreached `yaml:"unreached"`
	// Untouched are the tracked files the longest untouched.
	Untouched []Untouched `yaml:"untouched"`
}

// WidePR is a merged PR and how many files it touched.
type WidePR struct {
	PR    int    `yaml:"pr"`
	Title string `yaml:"title"`
	Files int    `yaml:"files"`
}

// Unreached is a function or method no caller reaches, and where it is.
type Unreached struct {
	Name  string `yaml:"name"`
	Place string `yaml:"place"`
}

// Untouched is a tracked file and when a commit last touched it.
type Untouched struct {
	Path string    `yaml:"path"`
	Last time.Time `yaml:"last"`
}

// prSubject is a squash merge's subject, ending in its PR's number.
var prSubject = regexp.MustCompile(`^(.*?)\s*\(#(\d+)\)$`)

// implicit are the method names a library calls without SE naming them.
var implicit = map[string]bool{
	"main": true, "init": true, "String": true, "Error": true, "Unwrap": true, "Is": true, "As": true, "Format": true,
	"MarshalJSON": true, "UnmarshalJSON": true, "MarshalYAML": true, "UnmarshalYAML": true, "MarshalText": true, "UnmarshalText": true,
	"Len": true, "Less": true, "Swap": true, "Read": true, "Write": true, "Close": true, "ServeHTTP": true, "IsBoolFlag": true, "Set": true,
}

// ReadCode reads the code facts of the checkout dir: its history from git on
// p, its Go code under src/ from d. The two reads run in parallel.
func ReadCode(p proc.Procs, d disk.Disk, dir string, since time.Time) (CodeFacts, error) {
	f := CodeFacts{Since: since}
	var (
		wg               sync.WaitGroup
		logged, tracked  string
		logErr, trackErr error
		walkErr          error
	)
	wg.Add(3)
	go func() {
		defer wg.Done()
		logged, logErr = proc.Output(p, proc.Cmd{Name: "git", Args: []string{"log", "--no-renames", "--format=%x1e%at%x1f%s", "--name-only", "HEAD"}, Dir: dir})
	}()
	go func() {
		defer wg.Done()
		tracked, trackErr = proc.Output(p, proc.Cmd{Name: "git", Args: []string{"ls-files"}, Dir: dir})
	}()
	go func() {
		defer wg.Done()
		f.Unreached, walkErr = unreached(d, dir)
	}()
	wg.Wait()
	for _, err := range []error{logErr, trackErr, walkErr} {
		if err != nil {
			return CodeFacts{}, err
		}
	}
	f.Widest, f.Untouched = history(logged, tracked, since)
	return f, nil
}

// history reads git log's records (each "\x1e<author time>\x1f<subject>" and the
// files it touched, newest first) and the tracked files: the widest PRs
// merged after since, and the tracked files the longest untouched.
func history(logged, tracked string, since time.Time) ([]WidePR, []Untouched) {
	last := map[string]time.Time{}
	widest := []WidePR{}
	for _, rec := range strings.Split(logged, "\x1e") {
		lines := strings.Split(strings.TrimSpace(rec), "\n")
		head, _, ok := strings.Cut(lines[0], "\x1f")
		secs, err := strconv.ParseInt(head, 10, 64)
		if !ok || err != nil {
			continue
		}
		at := time.Unix(secs, 0).UTC()
		files := 0
		for _, l := range lines[1:] {
			if l = strings.TrimSpace(l); l == "" {
				continue
			}
			files++
			if _, seen := last[l]; !seen {
				last[l] = at
			}
		}
		_, subject, _ := strings.Cut(lines[0], "\x1f")
		if m := prSubject.FindStringSubmatch(subject); m != nil && at.After(since) {
			widest = append(widest, WidePR{PR: atoi(m[2]), Title: m[1], Files: files})
		}
	}
	sort.SliceStable(widest, func(a, b int) bool { return widest[a].Files > widest[b].Files })
	untouched := []Untouched{}
	for _, path := range strings.Split(tracked, "\n") {
		if at, ok := last[path]; ok {
			untouched = append(untouched, Untouched{path, at})
		}
	}
	sort.Slice(untouched, func(a, b int) bool {
		if !untouched[a].Last.Equal(untouched[b].Last) {
			return untouched[a].Last.Before(untouched[b].Last)
		}
		return untouched[a].Path < untouched[b].Path
	})
	return widest[:min(len(widest), codeShown)], untouched[:min(len(untouched), codeShown)]
}

// unreached parses the Go files under dir's src/ and answers the top-level
// functions and methods outside tests whose name no other identifier there
// names, tests included. It matches by name alone, so a name used anywhere
// counts as reached: it misses some dead code and reports none that is live.
func unreached(d disk.Disk, dir string) ([]Unreached, error) {
	paths, err := d.Walk(filepath.Join(dir, "src"))
	if err != nil {
		return nil, err
	}
	fset := token.NewFileSet()
	named := map[string]int{}
	var declared []*ast.FuncDecl
	for _, p := range paths {
		if !strings.HasSuffix(p, ".go") {
			continue
		}
		text, err := d.ReadFile(p)
		if err != nil {
			return nil, err
		}
		file, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
		if err != nil {
			return nil, err
		}
		decl := map[*ast.Ident]bool{}
		if !strings.HasSuffix(p, "_test.go") {
			for _, x := range file.Decls {
				if fn, ok := x.(*ast.FuncDecl); ok && !implicit[fn.Name.Name] {
					declared = append(declared, fn)
					decl[fn.Name] = true
				}
			}
		}
		ast.Inspect(file, func(n ast.Node) bool {
			if id, ok := n.(*ast.Ident); ok && !decl[id] {
				named[id.Name]++
			}
			return true
		})
	}
	out := []Unreached{}
	for _, fn := range declared {
		if named[fn.Name.Name] > 0 {
			continue
		}
		pos := fset.Position(fn.Pos())
		rel, err := filepath.Rel(dir, pos.Filename)
		if err != nil {
			rel = pos.Filename
		}
		out = append(out, Unreached{Name: fn.Name.Name, Place: fmt.Sprintf("%s:%d", filepath.ToSlash(rel), pos.Line)})
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Place < out[b].Place })
	return out, nil
}

// text is the code facts as the draft shows them.
func (f CodeFacts) text() string {
	var b strings.Builder
	b.WriteString("\n## Single point of truth and locality: where to look\nPrinciples 2 and 3, over the whole system. Facts to start from, not findings: judge what is written twice, what no longer earns its place, and what was not used in a while.\n")
	since := "in the whole history"
	if !f.Since.IsZero() {
		since = "since the previous overhaul closed, " + f.Since.UTC().Format("2006-01-02") + ","
	}
	fmt.Fprintf(&b, "\nThe PRs merged %s that touched the most files:\n", since)
	if len(f.Widest) == 0 {
		b.WriteString("none.\n")
	} else {
		b.WriteString("\n| PR | title | files |\n|---|---|---|\n")
		for _, w := range f.Widest {
			fmt.Fprintf(&b, "| #%d | %s | %d |\n", w.PR, w.Title, w.Files)
		}
	}
	b.WriteString("\nCode no caller reaches (a function or method under src/ whose name nothing else names, tests included):\n")
	if len(f.Unreached) == 0 {
		b.WriteString("none.\n")
	} else {
		b.WriteString("\n")
		for _, u := range f.Unreached {
			fmt.Fprintf(&b, "- `%s` at %s\n", u.Name, u.Place)
		}
	}
	b.WriteString("\nThe files the longest untouched:\n")
	if len(f.Untouched) == 0 {
		b.WriteString("none.\n")
	} else {
		b.WriteString("\n| file | last touched |\n|---|---|\n")
		for _, u := range f.Untouched {
			fmt.Fprintf(&b, "| %s | %s |\n", u.Path, u.Last.Format("2006-01-02"))
		}
	}
	return b.String()
}
