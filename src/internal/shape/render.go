package shape

import (
	"fmt"
	"strings"
	"time"
)

// Top is how many of a long list the draft shows; it says how many more.
const Top = 10

// Markdown is the facts as the overhaul draft's text: each a candidate the
// judgment weighs, none a verdict.
func (f Facts) Markdown() string {
	var b strings.Builder
	b.WriteString("## Pruning and code shape\nCandidates, not verdicts: the overhaul agent's pruning rules (src/plugin/agents/overhaul.md) and spec/principles.md's \"How code is written\" judge them. They are also where to start on principles 2 and 3, which the overhaul judges over all the code, old and untouched included: the widest changes, what nothing reaches, what was not touched in a while. Each removal or reshaping is a finding with area `removal` or `principle`.\n")

	section(&b, "Production-unreachable", "What `deadcode ./...` finds nothing in production reaches, the fakes and test helpers left out: code only tests reach.")
	if f.Unrun != "" {
		fmt.Fprintf(&b, "Not found: %s.\n", f.Unrun)
	} else {
		places(&b, f.Unreachable)
	}

	section(&b, "Duplicates", fmt.Sprintf("Function bodies the same token for token (%d tokens or more).", minTokens))
	pairs(&b, f.Duplicates)
	section(&b, "Near-duplicates", fmt.Sprintf("Function bodies of the same shape, names and literals aside, %d%% alike or more: one generic piece with its variants as configuration could replace them.", nearAlike))
	pairs(&b, f.Near)

	section(&b, "Size", "Lines of Go that are not blank.")
	ratio := 0.0
	if f.Lines > 0 {
		ratio = float64(f.TestLines) / float64(f.Lines)
	}
	fmt.Fprintf(&b, "All: %d lines of code, %d of tests, a test ratio of %.2f.\n\n", f.Lines, f.TestLines, ratio)
	sizes(&b, "module", f.Modules)
	b.WriteString("\n")
	sizes(&b, "package", f.Packages)

	section(&b, "One-user abstractions", "A library one other module imports, a registry with one entry, an interface with one implementation and no fake.")
	places(&b, append(append(append([]Place{}, f.Libraries...), f.Registries...), f.Interfaces...))

	window := "in the whole history"
	if !f.Since.IsZero() {
		window = "since " + f.Since.Format("2006-01-02")
	}
	section(&b, "Unused surfaces", "The se commands, and the flags of those named, that no landing answer names "+window+" (the daemon's calls do not reach GitHub, so the landing answers stand in).")
	if len(f.Unused) == 0 {
		b.WriteString("None.\n")
	} else {
		b.WriteString("`" + strings.Join(f.Unused, "`, `") + "`.\n")
	}

	section(&b, "Legacy states", "Comments that say the code serves a state from before: check whether that state still occurs.")
	places(&b, f.Legacy)

	section(&b, "Scripts", "The files in src/scripts, why each was needed, and whether the last retro has read it.")
	list(&b, f.Scripts, func(s Script) string {
		read := "not read by a retro yet"
		if s.Read {
			read = "read by the last retro"
		}
		line := fmt.Sprintf("%s (%s, added %s): %s", s.Path, read, day(s.Added), s.Why)
		if len(s.Names) > 0 {
			line += "; it names " + strings.Join(s.Names, ", ")
		}
		return line
	})

	section(&b, "Untouched longest", "The tracked files with no change in the longest time.")
	list(&b, f.Untouched, func(t Touched) string { return t.Path + ", last changed " + day(t.Last) })

	section(&b, "Longest functions", "")
	measures(&b, f.LongFuncs, "lines")
	section(&b, "Longest files", "")
	measures(&b, f.LongFiles, "lines")
	section(&b, "Longest parameter lists", "")
	measures(&b, f.LongParams, "parameters")
	section(&b, "Switches on a kind", fmt.Sprintf("Switches with %d arms or more: a table or a registry may fit better.", kindArms))
	measures(&b, f.Switches, "arms")

	section(&b, "Files touched per change", "Shotgun surgery: one change in many files.")
	if f.Changes == 0 {
		b.WriteString("No change on main to read.\n")
	} else {
		fmt.Fprintf(&b, "Over the last %d changes on main: a median of %d files, at most %d. The widest:\n\n", f.Changes, f.MedianFiles, f.MaxFiles)
		list(&b, f.Widest, func(c Change) string { return fmt.Sprintf("%d files: %s (%s)", c.Files, c.Subject, short(c.SHA)) })
	}
	return b.String()
}

func section(b *strings.Builder, title, what string) {
	fmt.Fprintf(b, "\n### %s\n", title)
	if what != "" {
		b.WriteString(what + "\n")
	}
	b.WriteString("\n")
}

// list writes the first Top items, each as line says, and how many more.
func list[T any](b *strings.Builder, items []T, line func(T) string) {
	if len(items) == 0 {
		b.WriteString("None.\n")
		return
	}
	for k, it := range items {
		if k == Top {
			fmt.Fprintf(b, "- and %d more\n", len(items)-Top)
			break
		}
		b.WriteString("- " + line(it) + "\n")
	}
}

func places(b *strings.Builder, ps []Place) {
	list(b, ps, func(p Place) string { return p.At + ": " + p.What })
}

func pairs(b *strings.Builder, ps []Pair) {
	list(b, ps, func(p Pair) string {
		return fmt.Sprintf("%s (%s) and %s (%s), %d%% alike", p.A.What, p.A.At, p.B.What, p.B.At, p.Alike)
	})
}

func measures(b *strings.Builder, ms []Measure, unit string) {
	list(b, ms, func(m Measure) string { return fmt.Sprintf("%d %s: %s (%s)", m.N, unit, m.What, m.At) })
}

func sizes(b *strings.Builder, kind string, zs []Size) {
	fmt.Fprintf(b, "| %s | code | tests | ratio | share |\n|---|---|---|---|---|\n", kind)
	for _, z := range zs {
		ratio := "–"
		if z.Lines > 0 {
			ratio = fmt.Sprintf("%.2f", float64(z.TestLines)/float64(z.Lines))
		}
		fmt.Fprintf(b, "| %s | %d | %d | %s | %d%% |\n", z.Name, z.Lines, z.TestLines, ratio, z.Share)
	}
}

func day(t time.Time) string {
	if t.IsZero() {
		return "at no known time"
	}
	return t.Format("2006-01-02")
}

func short(sha string) string {
	if len(sha) > 7 {
		return sha[:7]
	}
	return sha
}
