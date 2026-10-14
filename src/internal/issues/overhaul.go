package issues

import (
	"errors"
	"fmt"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// PrinciplesFile is where the design principles live, relative to a
// checkout: the overhaul judges SE against every one of them.
const PrinciplesFile = "spec/principles.md"

// overhaulUnattendedMark is in the body of an overhaul no person started. One
// a person started carries <!-- se:overhaul attended --> instead. Either way
// its box files the issues and closes it.
const overhaulUnattendedMark = "<!-- se:overhaul unattended -->"

// The marks that cut an overhaul's report into its parts: the report, the
// facts se overhaul read wrote, and the machine-readable block.
const (
	overhaulReportMark = "<!-- se:overhaul-report -->"
	overhaulFactsMark  = "<!-- se:overhaul-facts -->"
	overhaulBlock      = "<!-- se:overhaul-yaml -->"
)

// OverhaulIssue is the overhaul se overhaul new created.
type OverhaulIssue struct {
	Issue
	// Previous is the last closed overhaul; 0 where none has closed.
	Previous   int  `json:"previous"`
	Unattended bool `json:"unattended"`
}

// NewOverhaul creates an overhaul issue, labelled se and se-overhaul;
// unattended says nobody waits for its report. It goes through the same code
// as se issue new.
func (s Source) NewOverhaul(unattended bool) (OverhaulIssue, error) {
	last, ok, _, err := s.lastClosed(OverhaulLabel, 0)
	if err != nil {
		return OverhaulIssue{}, err
	}
	o := OverhaulIssue{Unattended: unattended}
	before := "It is the first overhaul."
	if ok {
		o.Previous = last.Number
		before = fmt.Sprintf("The last overhaul was #%d; this one compares against its report.", last.Number)
	}
	mode, who := "attended", "A person started it. The box creates the findings' issues, those for a person where controversial, and closes it."
	if unattended {
		mode, who = "unattended", "It runs unattended. The box creates the findings' issues, those for a person where controversial, and closes it."
	}
	body := fmt.Sprintf("An overhaul of SE as it stands: is the design still right? It checks every design principle, the outside world, the consistency of the whole system, the principles themselves and the retro's last %d runs. The rules are spec/overhaul.md; a box takes it with the overhaul skill and starts with `se overhaul read`.\n\n%s %s\n\n<!-- se:overhaul %s -->",
		OverhaulCadence, before, who, mode)
	made, _, err := s.create("SE overhaul "+s.now().UTC().Format("2006-01-02"), body, 0, nil, []string{Label, OverhaulLabel})
	if err != nil {
		return OverhaulIssue{}, err
	}
	o.Issue = made
	return o, nil
}

// Principle is one design principle, as spec/principles.md states it.
type Principle struct {
	Number    int    `yaml:"number"`
	Name      string `yaml:"name"`
	CheckedBy string `yaml:"checked_by"`
	// Mechanical says the retro or the battery checks it mechanically, so
	// the latest retros' rule checks and metrics speak to it; the rest the
	// overhaul judges by reading the code and spec against its text.
	Mechanical bool `yaml:"mechanical"`
}

var (
	principleLine = regexp.MustCompile(`^\s*(\d+)\.\s+\*\*(.+?)\*\*`)
	checkedLine   = regexp.MustCompile(`^\s*Checked by:\s*(.+)$`)
)

// Principles reads the design principles from the checkout dir on d.
func Principles(d disk.Disk, dir string) ([]Principle, error) {
	path := filepath.Join(dir, PrinciplesFile)
	data, err := d.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("the design principles: %w", err)
	}
	var ps []Principle
	// checked says the line before belongs to a "Checked by:" text, which
	// runs on over indented lines until a blank line or the next principle.
	checked := false
	for _, line := range strings.Split(string(data), "\n") {
		if m := principleLine.FindStringSubmatch(line); m != nil {
			ps = append(ps, Principle{Number: atoi(m[1]), Name: strings.TrimSuffix(m[2], ".")})
			checked = false
			continue
		}
		if m := checkedLine.FindStringSubmatch(line); m != nil && len(ps) > 0 {
			ps[len(ps)-1].CheckedBy = strings.TrimSpace(m[1])
			checked = true
			continue
		}
		if checked && strings.TrimSpace(line) != "" && strings.TrimLeft(line, " \t") != line {
			ps[len(ps)-1].CheckedBy += " " + strings.TrimSpace(line)
			continue
		}
		checked = false
	}
	for i := range ps {
		p := &ps[i]
		p.Mechanical = strings.Contains(p.CheckedBy, "mechanically") || strings.Contains(p.CheckedBy, "battery")
	}
	if len(ps) == 0 {
		return nil, fmt.Errorf("%s states no principle", path)
	}
	return ps, nil
}

// RetroRun is one of the latest retros, as its closing report tells it.
type RetroRun struct {
	Retro   int     `yaml:"retro"`
	Metrics Metrics `yaml:"metrics"`
	// Broken counts its broken rule checks, by kind.
	Broken map[string]int `yaml:"broken"`
	// Findings counts its findings, Issues those that became issues, and
	// Closed those issues closed as completed by now.
	Findings int `yaml:"findings"`
	Issues   int `yaml:"issues"`
	Closed   int `yaml:"closed"`
	// Recurred counts its findings the next retro found recurred anyway.
	Recurred int      `yaml:"recurred"`
	Classes  []string `yaml:"classes"`
}

// Overhauled is one finding of the previous overhaul and what became of it.
type Overhauled struct {
	Title     string `yaml:"title"`
	Principle int    `yaml:"principle,omitempty"`
	Issue     int    `yaml:"issue,omitempty"`
	// State is its issue's: open, completed, not_planned, or none.
	State string `yaml:"state"`
}

// OverhaulReport is an overhaul's machine-readable block. se overhaul read
// fills the facts; the box fills Verdicts, LookedAt, Findings and WentWell;
// se overhaul file fills each finding's Issue. The next overhaul reads it
// first.
type OverhaulReport struct {
	Overhaul   int         `yaml:"overhaul"`
	Attended   bool        `yaml:"attended"`
	Until      time.Time   `yaml:"until"`
	Previous   int         `yaml:"previous,omitempty"`
	Principles []Principle `yaml:"principles"`
	Retros     []RetroRun  `yaml:"retros"`
	// Recurring are the finding classes more than one of the latest retros
	// named: findings that recurred anyway.
	Recurring []string     `yaml:"recurring"`
	Earlier   []Overhauled `yaml:"earlier"`
	// Code is what the checkout says on principles 2 and 3; se overhaul read
	// reads it with ReadCode, from Code.Since, which CollectOverhaul sets.
	Code CodeFacts `yaml:"code"`
	// Verdicts, LookedAt, Findings and WentWell are the box's judgment.
	Verdicts []Judged   `yaml:"verdicts"`
	LookedAt LookedAt   `yaml:"looked_at"`
	Findings []Straying `yaml:"findings"`
	WentWell []string   `yaml:"went_well"`
}

// Judged is the box's judgment of one principle: how far SE strays from it.
type Judged struct {
	Principle int `yaml:"principle"`
	// Strays is none, slightly or far.
	Strays string `yaml:"strays"`
	How    string `yaml:"how"`
}

// LookedAt says what the box found beyond the principles one by one: the
// outside world, the consistency of the whole system, the principles
// themselves, the retro's effectiveness, what could be faster (run in
// parallel, ask the server for more per query), what an agent still does that
// could be a command, and what could go. Each is required, "nothing to
// change" included.
type LookedAt struct {
	Outside     string `yaml:"outside"`
	Consistency string `yaml:"consistency"`
	Principles  string `yaml:"principles"`
	Retro       string `yaml:"retro"`
	Speed       string `yaml:"speed"`
	Mechanize   string `yaml:"mechanize"`
	Removal     string `yaml:"removal"`
}

// Straying is one finding of an overhaul: where SE strays, from which
// principle, and how far. It becomes an issue.
type Straying struct {
	Title string `yaml:"title"`
	Body  string `yaml:"body"`
	// Area is what found it: principle, outside, consistency, principles
	// (a change to a principle), retro, speed, mechanize or removal.
	Area string `yaml:"area"`
	// Principle is the principle it names; 0 only for a principle missing
	// from the list.
	Principle int `yaml:"principle"`
	// Place is where in SE it is, or what it would change.
	Place string `yaml:"place"`
	// Strays is how far: slightly or far.
	Strays string `yaml:"strays"`
	// Sources are the outside sources it cites; an outside finding needs one.
	Sources       []string `yaml:"sources,omitempty"`
	Controversial bool     `yaml:"controversial"`
	Why           string   `yaml:"why,omitempty"`
	Issue         int      `yaml:"issue,omitempty"`
}

var (
	areas      = []string{"principle", "outside", "consistency", "principles", "retro", "speed", "mechanize", "removal"}
	verdicts   = []string{"none", "slightly", "far"}
	principled = "it changes a design principle"
)

// overhaulIssue reads overhaul n: it must be an open issue labelled se-overhaul.
func (s Source) overhaulIssue(n int) (issue, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return issue{}, err
	}
	i := got[0]
	if i.PullRequest != nil || i.State != "open" || !i.labelled(OverhaulLabel) {
		return issue{}, fmt.Errorf("#%d is not an open overhaul (an issue labelled %s)", n, OverhaulLabel)
	}
	return i, nil
}

// CollectOverhaul reads overhaul n's facts from GitHub: the principles ps,
// the latest retros' reports and how their findings fared, and the previous
// overhaul's findings and when it closed. The code facts ReadCode reads.
func (s Source) CollectOverhaul(n int, ps []Principle) (OverhaulReport, error) {
	i, err := s.overhaulIssue(n)
	if err != nil {
		return OverhaulReport{}, err
	}
	r := OverhaulReport{
		Overhaul: n, Attended: !strings.Contains(i.Body, overhaulUnattendedMark), Until: s.now().UTC().Truncate(time.Second),
		Principles: ps, Retros: []RetroRun{}, Recurring: []string{}, Earlier: []Overhauled{},
		Verdicts: []Judged{}, Findings: []Straying{}, WentWell: []string{},
	}
	_, _, retros, err := s.lastClosed(RetroLabel, 0)
	if err != nil {
		return OverhaulReport{}, err
	}
	var reports []*RetroReport
	for k := len(retros) - 1; k >= 0 && len(reports) < OverhaulCadence; k-- {
		rep, err := s.postedReport(retros[k].Number)
		if err != nil {
			return OverhaulReport{}, err
		}
		if rep != nil {
			reports = append([]*RetroReport{rep}, reports...)
		}
	}
	named := map[string]int{}
	for k, rep := range reports {
		run := RetroRun{Retro: rep.Retro, Metrics: rep.Metrics, Broken: map[string]int{}, Findings: len(rep.Findings), Classes: []string{}}
		for _, c := range rep.Checks {
			run.Broken[c.Kind]++
		}
		for _, f := range rep.Findings {
			if f.Issue == 0 {
				continue
			}
			run.Issues++
			state, err := s.state(f.Issue)
			if err != nil {
				return OverhaulReport{}, err
			}
			if state == "completed" {
				run.Closed++
			}
		}
		if k+1 < len(reports) && reports[k+1].Previous != nil {
			run.Recurred = reports[k+1].Previous.Recurred
		}
		for _, c := range rep.Classes {
			run.Classes = append(run.Classes, c.Name)
			named[c.Name]++
		}
		r.Retros = append(r.Retros, run)
	}
	for name, times := range named {
		if times > 1 {
			r.Recurring = append(r.Recurring, name)
		}
	}
	sort.Strings(r.Recurring)
	last, ok, _, err := s.lastClosed(OverhaulLabel, n)
	if err != nil || !ok {
		return r, err
	}
	r.Previous, r.Code.Since = last.Number, last.ClosedAt.UTC()
	text, err := s.lastPosted(last.Number, overhaulReportMark)
	if err != nil || text == "" {
		return r, err
	}
	prev, _, err := ParseOverhaul(text)
	if err != nil {
		return OverhaulReport{}, fmt.Errorf("the report on #%d: %w", last.Number, err)
	}
	for _, f := range prev.Findings {
		o := Overhauled{Title: f.Title, Principle: f.Principle, Issue: f.Issue, State: "none"}
		if f.Issue > 0 {
			if o.State, err = s.state(f.Issue); err != nil {
				return OverhaulReport{}, err
			}
		}
		r.Earlier = append(r.Earlier, o)
	}
	return r, nil
}

// state is issue n's state: open, or the reason it closed.
func (s Source) state(n int) (string, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return "", err
	}
	if got[0].State == "closed" {
		return got[0].StateReason, nil
	}
	return got[0].State, nil
}

// OverhaulDraft is the report draft se overhaul read writes: the facts as
// text and the block, its judgment left to the box.
func (r OverhaulReport) OverhaulDraft() (string, error) { return r.assemble(r.facts()) }

// facts is the mechanical half of the overhaul's report as text.
func (r OverhaulReport) facts() string {
	var b strings.Builder
	b.WriteString("## The principles\nEvery one gets a verdict. The mechanical ones the latest retros' rule checks and metrics speak to; the rest are judged by reading the code and spec against the principle's text.\n\n| # | principle | checked by | how |\n|---|---|---|---|\n")
	for _, p := range r.Principles {
		how := "judgment"
		if p.Mechanical {
			how = "mechanical, and judgment"
		}
		fmt.Fprintf(&b, "| %d | %s | %s | %s |\n", p.Number, p.Name, p.CheckedBy, how)
	}

	fmt.Fprintf(&b, "\n## The retro's last %d runs\n", OverhaulCadence)
	if len(r.Retros) == 0 {
		b.WriteString("No retro has a report yet.\n")
	} else {
		b.WriteString("| metric |")
		for _, run := range r.Retros {
			fmt.Fprintf(&b, " #%d |", run.Retro)
		}
		b.WriteString("\n|---|" + strings.Repeat("---|", len(r.Retros)) + "\n")
		for _, name := range metricNames {
			fmt.Fprintf(&b, "| %s |", name)
			for _, run := range r.Retros {
				if v, ok := run.Metrics[name]; ok {
					fmt.Fprintf(&b, " %g |", v)
				} else {
					b.WriteString(" – |")
				}
			}
			b.WriteString("\n")
		}
		for _, k := range checkKinds {
			fmt.Fprintf(&b, "| broken `%s` |", k.Kind)
			for _, run := range r.Retros {
				fmt.Fprintf(&b, " %d |", run.Broken[k.Kind])
			}
			b.WriteString("\n")
		}
		b.WriteString("\n| retro | findings | became issues | closed | recurred anyway |\n|---|---|---|---|---|\n")
		for _, run := range r.Retros {
			fmt.Fprintf(&b, "| #%d | %d | %d | %d | %d |\n", run.Retro, run.Findings, run.Issues, run.Closed, run.Recurred)
		}
		recurring := "none"
		if len(r.Recurring) > 0 {
			recurring = strings.Join(r.Recurring, ", ")
		}
		fmt.Fprintf(&b, "\nClasses more than one of them named: %s.\n", recurring)
	}

	b.WriteString("\n## The previous overhaul\n")
	switch {
	case r.Previous == 0:
		b.WriteString("None: this is the first overhaul.\n")
	case len(r.Earlier) == 0:
		fmt.Fprintf(&b, "#%d left no findings.\n", r.Previous)
	default:
		fmt.Fprintf(&b, "#%d found:\n\n| finding | principle | issue | state |\n|---|---|---|---|\n", r.Previous)
		for _, o := range r.Earlier {
			issue := "–"
			if o.Issue > 0 {
				issue = "#" + strconv.Itoa(o.Issue)
			}
			fmt.Fprintf(&b, "| %s | %d | %s | %s |\n", o.Title, o.Principle, issue, o.State)
		}
	}
	b.WriteString(r.Code.text())
	return b.String()
}

// assemble is the report as text: the judgment rendered from the block, then
// the facts, then the block.
func (r OverhaulReport) assemble(facts string) (string, error) {
	data, err := yaml.Marshal(r)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s\n# Overhaul #%d: the report\n\n%s\n%s\n%s\n\n%s\n```yaml\n%s```\n",
		overhaulReportMark, r.Overhaul, r.judgment(), overhaulFactsMark, strings.TrimSpace(facts), overhaulBlock, data), nil
}

// judgment renders the box's half of the report from the block.
func (r OverhaulReport) judgment() string {
	if len(r.Verdicts) == 0 && len(r.Findings) == 0 {
		return "The box judges here: it fills `verdicts`, `looked_at`, `findings` and `went_well` in the block below, and `se overhaul file` writes this part from them.\n"
	}
	var b strings.Builder
	b.WriteString("## The principles, one by one\n| # | principle | strays | how |\n|---|---|---|---|\n")
	names := map[int]string{}
	for _, p := range r.Principles {
		names[p.Number] = p.Name
	}
	for _, v := range r.Verdicts {
		fmt.Fprintf(&b, "| %d | %s | %s | %s |\n", v.Principle, names[v.Principle], v.Strays, oneLine(v.How))
	}
	b.WriteString("\n## Findings\n")
	if len(r.Findings) == 0 {
		b.WriteString("None.\n")
	}
	for _, area := range areas {
		for _, f := range r.Findings {
			if f.Area == area {
				b.WriteString(f.line())
			}
		}
	}
	fmt.Fprintf(&b, "\n## Beyond the principles\n- **The outside world:** %s\n- **Consistency across the whole system:** %s\n- **The principles themselves:** %s\n- **The retro's effectiveness:** %s\n- **Speed (what could run in parallel, or ask the server for more at once):** %s\n- **Mechanize (what an agent still does that could be an se command):** %s\n- **Removal (what could go):** %s\n",
		oneLine(r.LookedAt.Outside), oneLine(r.LookedAt.Consistency), oneLine(r.LookedAt.Principles), oneLine(r.LookedAt.Retro),
		oneLine(r.LookedAt.Speed), oneLine(r.LookedAt.Mechanize), oneLine(r.LookedAt.Removal))
	b.WriteString("\n## What went well\n")
	for _, w := range r.WentWell {
		fmt.Fprintf(&b, "- %s\n", w)
	}
	return b.String()
}

func oneLine(s string) string { return strings.Join(strings.Fields(s), " ") }

func (f Straying) line() string {
	who := "normal queue"
	if f.Controversial {
		who = "for a person: " + f.Why
	}
	s := fmt.Sprintf("- **%s** (%s, principle %d, strays %s, at %s; %s)", f.Title, f.Area, f.Principle, f.Strays, f.Place, who)
	if f.Issue > 0 {
		s += fmt.Sprintf(": #%d", f.Issue)
	}
	s += "\n  " + strings.ReplaceAll(strings.TrimSpace(f.Body), "\n", "\n  ") + "\n"
	for _, src := range f.Sources {
		s += "  - source: " + src + "\n"
	}
	return s
}

// ParseOverhaul reads an overhaul's report, a draft or a posted one, back:
// its block and its facts as text.
func ParseOverhaul(text string) (r OverhaulReport, facts string, err error) {
	if !strings.Contains(text, overhaulReportMark) {
		return OverhaulReport{}, "", errors.New("it is no overhaul report: the mark " + overhaulReportMark + " is missing")
	}
	head, rest, ok := strings.Cut(text, overhaulBlock+"\n```yaml\n")
	if !ok {
		return OverhaulReport{}, "", errors.New("the report carries no machine-readable block under " + overhaulBlock)
	}
	block, _, ok := strings.Cut("\n"+rest, "\n```")
	if !ok {
		return OverhaulReport{}, "", errors.New("the report's block is not closed")
	}
	if err := yaml.Unmarshal([]byte(block), &r); err != nil {
		return OverhaulReport{}, "", fmt.Errorf("the report's block: %v", err)
	}
	if _, f, ok := strings.Cut(head, overhaulFactsMark); ok {
		facts = f
	}
	return r, strings.TrimSpace(facts), nil
}

// judged refuses an overhaul whose judgment is not complete: a verdict for
// every principle, each how far it strays and how; something said on each
// thing beyond the principles; every finding a title, a body, a known area,
// the principle it names, its place, how far it strays, a source where it
// comes from outside, and a reason where it is controversial; and something
// that went well. A change to a principle is made controversial.
func (r *OverhaulReport) judged() error {
	var why []string
	known := map[int]bool{}
	for _, p := range r.Principles {
		known[p.Number] = true
	}
	judgedAs := map[int]bool{}
	for _, v := range r.Verdicts {
		switch {
		case !known[v.Principle]:
			why = append(why, fmt.Sprintf("a verdict names principle %d, which the list does not", v.Principle))
		case !contains(verdicts, v.Strays) || strings.TrimSpace(v.How) == "":
			why = append(why, fmt.Sprintf("the verdict on principle %d needs strays (%s) and how", v.Principle, strings.Join(verdicts, ", ")))
		}
		judgedAs[v.Principle] = true
	}
	for _, p := range r.Principles {
		if !judgedAs[p.Number] {
			why = append(why, fmt.Sprintf("principle %d (%s) has no verdict", p.Number, p.Name))
		}
	}
	for name, said := range map[string]string{
		"outside": r.LookedAt.Outside, "consistency": r.LookedAt.Consistency, "principles": r.LookedAt.Principles, "retro": r.LookedAt.Retro,
		"speed": r.LookedAt.Speed, "mechanize": r.LookedAt.Mechanize, "removal": r.LookedAt.Removal,
	} {
		if strings.TrimSpace(said) == "" {
			why = append(why, "looked_at."+name+" is empty: say what was found, nothing included")
		}
	}
	for k := range r.Findings {
		f := &r.Findings[k]
		if f.Area == "principles" {
			f.Controversial = true
			if strings.TrimSpace(f.Why) == "" {
				f.Why = principled
			}
		}
		name := fmt.Sprintf("finding %d (%q)", k+1, f.Title)
		switch {
		case strings.TrimSpace(f.Title) == "" || strings.TrimSpace(f.Body) == "":
			why = append(why, name+" needs a title and a body")
		case !contains(areas, f.Area):
			why = append(why, fmt.Sprintf("%s has area %q, not one of %s", name, f.Area, strings.Join(areas, ", ")))
		case !known[f.Principle] && (f.Area != "principles" || f.Principle != 0):
			why = append(why, fmt.Sprintf("%s names principle %d, which the list does not (0 only for a missing principle)", name, f.Principle))
		case strings.TrimSpace(f.Place) == "":
			why = append(why, name+" names no place")
		case f.Strays != "slightly" && f.Strays != "far":
			why = append(why, name+" needs strays: slightly or far")
		case f.Area == "outside" && len(f.Sources) == 0:
			why = append(why, name+" comes from outside without a source")
		case f.Controversial && strings.TrimSpace(f.Why) == "":
			why = append(why, name+" is controversial without a why")
		}
	}
	if len(r.WentWell) == 0 {
		why = append(why, "went_well is empty: record what went well")
	}
	if len(why) == 0 {
		return nil
	}
	sort.Strings(why)
	return fmt.Errorf("the overhaul's judgment is not complete, so nothing was written: %s", strings.Join(why, "; "))
}

// PostedOverhaul is the report already on overhaul n, posted for the owner
// before overhauls stopped waiting, for the box that files it; "" where there
// is none.
func (s Source) PostedOverhaul(n int) (string, error) {
	if _, err := s.overhaulIssue(n); err != nil {
		return "", err
	}
	text, err := s.lastPosted(n, overhaulReportMark)
	return text, err
}

// FileOverhaul files overhaul n's report, the text of a draft the box judged,
// as a retro's is filed (spec/retro.md): its findings become issues, one for
// a person where controversial, and it closes.
func (s Source) FileOverhaul(n int, draft string) (Filed, error) {
	r, facts, err := ParseOverhaul(draft)
	if err != nil {
		return Filed{}, err
	}
	if r.Overhaul != n {
		return Filed{}, fmt.Errorf("the report is overhaul #%d's, not #%d's", r.Overhaul, n)
	}
	if err := r.judged(); err != nil {
		return Filed{}, err
	}
	i, err := s.overhaulIssue(n)
	if err != nil {
		return Filed{}, err
	}
	run := filing{kind: "overhaul", mark: overhaulReportMark, assemble: func() (string, error) { return r.assemble(facts) }}
	run.mint = func(out *Filed) error {
		for k := range r.Findings {
			f := &r.Findings[k]
			if f.Issue > 0 {
				continue
			}
			body := fmt.Sprintf("%s\n\nFound by the overhaul #%d (%s): it strays %s from principle %d, at %s.", strings.TrimSpace(f.Body), n, f.Area, f.Strays, f.Principle, f.Place)
			if len(f.Sources) > 0 {
				body += "\n\nSources: " + strings.Join(f.Sources, ", ")
			}
			var err error
			if f.Issue, err = s.mint(f.Title, body, f.Controversial, f.Why, out); err != nil {
				return err
			}
		}
		return nil
	}
	return s.fileRun(i, run)
}
