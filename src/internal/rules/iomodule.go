package rules

import (
	"fmt"
	"path"
	"sort"
	"strings"
)

// Allowlist names the places that still go around a door, one per line: a
// file and what it names, a Go name or a command word a door declares. It
// only shrinks: an entry that matches nothing is refused.
const Allowlist = IODir + "/allowlist.txt"

func init() {
	register(Rule{
		Name: "io-module",
		Doc: "every I/O module under " + IODir + " declares in its " + DoorFile + " the resource it guards, the Go names that reach it (go) " +
			"and the words that reach it from a shell or an agent's text (commands); no Go file outside " + IODir + " uses a go name, or starts a program a commands word names, " +
			"and no plugin agent, skill or hook, script under src/scripts, tests/*.sh or CLAUDE.md names a commands word, except on a line marked " +
			Marker + " - <why> or as " + Allowlist + " names; an entry there that matches nothing, a marker without a reason and one that passes nothing are refused",
		Applies: func(p string) bool {
			return p == Allowlist || doorOf(p) != "" || outsideGo(p) || toldToRun(p)
		},
		Check: ioModule,
	})
}

// outsideGo says whether p is Go code outside the doors.
func outsideGo(p string) bool {
	return path.Ext(p) == ".go" && !strings.HasSuffix(p, "_test.go") && !strings.HasPrefix(p, IODir+"/")
}

// toldToRun says whether p is text a box runs or is told to run: the
// plugin's agents, skills and hooks, the ad hoc scripts, the battery's shell
// files and CLAUDE.md.
func toldToRun(p string) bool {
	return strings.HasPrefix(p, "src/plugin/") || strings.HasPrefix(p, "src/scripts/") ||
		(path.Dir(p) == "tests" && path.Ext(p) == ".sh") || p == "CLAUDE.md"
}

func ioModule(repo *Repo, p string, text []byte) []Finding {
	ds := doorsOf(repo)
	switch {
	case p == Allowlist:
		return staleEntries(repo, text, Allowlist, "io-module", ds.reaches)
	case doorOf(p) != "":
		found := ds.faults[p]
		if at, bare := ds.bare[p]; bare {
			found = append(found, Finding{Path: p, Line: 1, Rule: "io-module", Message: fmt.Sprintf(
				"the I/O module %s declares nothing: write %s/%s, saying the resource it guards and what goes around it (spec/io.md)", at, at, DoorFile)})
		}
		return found
	}
	list, _, _ := repo.Read(Allowlist)
	allowed := map[string]bool{}
	for _, e := range entriesOf(list) {
		allowed[e.file+" "+e.reach] = true
	}
	var found []Finding
	walks := ds.walksOf(p, text, func(f Finding) { found = append(found, f) })
	for _, w := range walks {
		if allowed[p+" "+w.what] {
			continue
		}
		through := "go through it"
		if !strings.HasSuffix(p, ".go") {
			through = "go through se"
		}
		found = append(found, Finding{Path: p, Line: w.line, Rule: "io-module", Message: fmt.Sprintf(
			"%s reaches %s around its door (%s); %s (spec/io.md)", w.said, w.door.Resource(), w.door.At, through)})
	}
	return found
}

// walksOf answers every way the file goes around a door that no marker
// passes, and hands refuse each marker that is wrong: one without a reason,
// which passes nothing, and one on a line that goes around no door.
func (ds *doors) walksOf(p string, text []byte, refuse func(Finding)) []walk {
	var walks []walk
	var m marks
	if path.Ext(p) == ".go" {
		walks, m = ds.goWalks(p, text)
	} else {
		walks, m = ds.textWalks(text)
	}
	at := map[int]bool{}
	seen := map[string]bool{}
	var out []walk
	for _, w := range walks {
		at[w.line] = true
		key := fmt.Sprint(w.line, " ", w.what)
		if m[w.line] == "" && !seen[key] {
			seen[key] = true
			out = append(out, w)
		}
	}
	lines := make([]int, 0, len(m))
	for l := range m {
		lines = append(lines, l)
	}
	sort.Ints(lines)
	for _, l := range lines {
		msg := ""
		switch {
		case m[l] == "":
			msg = "the marker gives no reason, so it passes nothing: write " + Marker + " - <why>"
		case !at[l]:
			msg = "the marker passes nothing: the line goes around no door; remove it"
		}
		if msg != "" && refuse != nil {
			refuse(Finding{Path: p, Line: l, Rule: "io-module", Message: msg})
		}
	}
	return out
}

// reaches answers the file's walks as reaches, each what once, at its first
// line, in order: what an allowlist entry matches.
func (ds *doors) reaches(p string, text []byte) []Reach {
	first := map[string]int{}
	for _, w := range ds.walksOf(p, text, nil) {
		if l, ok := first[w.what]; !ok || w.line < l {
			first[w.what] = w.line
		}
	}
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
			refuse("an entry is a file and what it reaches, such as: src/cmd/se/x.go os/exec")
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

// Reach is one way a file reaches the outside: an import path, such as
// os/exec, a call, such as time.Now, or a program or command word, such as
// gh, and the first line it is on.
type Reach struct {
	What string
	Line int
}
