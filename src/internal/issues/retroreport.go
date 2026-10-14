package issues

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/mb-89/SE/src/internal/io/github"
)

// The marks that cut a retro's report into its parts: the report itself, the
// box's judgment (rendered from the block), the facts se retro collect wrote,
// the machine-readable block, and the matrix, which only the draft carries.
const (
	reportMark   = "<!-- se:retro-report -->"
	judgmentMark = "<!-- se:retro-judgment -->"
	factsMark    = "<!-- se:retro-facts -->"
	reportBlock  = "<!-- se:retro-yaml -->"
	matrixMark   = "<!-- se:retro-matrix -->"
)

// RetroReport is a retro's machine-readable block. se retro collect fills the
// facts; the box fills Findings, Classes and WentWell; se retro report fills
// each finding's Issue. The next retro reads it first.
type RetroReport struct {
	Retro    int         `yaml:"retro"`
	Attended bool        `yaml:"attended"`
	Window   RetroWindow `yaml:"window"`
	Metrics  Metrics     `yaml:"metrics"`
	Checks   []Broken    `yaml:"checks"`
	Previous *Score      `yaml:"previous,omitempty"`
	// Findings, Classes and WentWell are the box's judgment.
	Findings []Lesson `yaml:"findings"`
	Classes  []Class  `yaml:"classes"`
	WentWell []string `yaml:"went_well"`
}

// Lesson is one finding of a retro: what went wrong, the class it belongs to,
// and the fix it asks for. It becomes an issue.
type Lesson struct {
	Title string `yaml:"title"`
	Class string `yaml:"class"`
	Body  string `yaml:"body"`
	// Home is the fix's kind, cheapest durable first: check, refusal, gate,
	// field (a prefilled one), command (an se command for a step done by
	// hand), guidance, or removal.
	Home string `yaml:"home"`
	// Controversial sends its issue to a person; Why says which rule makes it so.
	Controversial bool   `yaml:"controversial"`
	Why           string `yaml:"why,omitempty"`
	// Check is the rule check it answers, Metric the metric it should move;
	// the next retro scores it by them.
	Check  string `yaml:"check,omitempty"`
	Metric string `yaml:"metric,omitempty"`
	// Retro marks a finding about the retro itself.
	Retro bool `yaml:"retro,omitempty"`
	// Issue is the issue it became.
	Issue int `yaml:"issue,omitempty"`
}

// Class is a group of findings of one kind and its cheapest durable fix.
type Class struct {
	Name string `yaml:"name"`
	Fix  string `yaml:"fix"`
}

// homes are the kinds of fix a finding may ask for, in order of preference.
var homes = []string{"check", "refusal", "gate", "field", "command", "guidance", "removal"}

// Draft is the report draft se retro collect writes: the facts as text, the
// block, and the matrix below it.
func (c Collected) Draft(qs []Question) (string, error) {
	r := RetroReport{
		Retro: c.Retro, Attended: c.Attended, Window: c.Window, Metrics: c.Metrics, Checks: c.Checks,
		Previous: c.Score, Findings: []Lesson{}, Classes: []Class{}, WentWell: []string{},
	}
	if r.Checks == nil {
		r.Checks = []Broken{}
	}
	var b strings.Builder
	b.WriteString(c.facts())
	text, err := r.assemble(b.String())
	if err != nil {
		return "", err
	}
	return text + "\n" + matrixMark + "\n" + c.matrix(qs), nil
}

// facts is the mechanical half of the report as text.
func (c Collected) facts() string {
	var b strings.Builder
	w := c.Window
	scope := "The repository's whole history: no retro has closed before"
	if w.Previous > 0 {
		scope = fmt.Sprintf("Everything closed since the retro #%d closed, %s", w.Previous, w.Since.Format(time.RFC3339))
	}
	fmt.Fprintf(&b, "## The window\n%s, up to %s: %d closed `se` issues, %d merged PRs, %d commits on main.\n",
		scope, w.Until.Format(time.RFC3339), len(c.Rows), c.PRs, c.Commits)

	b.WriteString("\n## Rule checks\n")
	for _, k := range checkKinds {
		var broke []Broken
		for _, x := range c.Checks {
			if x.Kind == k.Kind {
				broke = append(broke, x)
			}
		}
		before := ""
		if n := c.Before[k.Kind]; n > 0 {
			before = fmt.Sprintf(" Before the rule came with PR #%d: broken %s, not counted.", k.Since, count(n))
		}
		if len(broke) == 0 {
			fmt.Fprintf(&b, "- **%s** (`%s`): held.%s\n", k.Rule, k.Kind, before)
			continue
		}
		fmt.Fprintf(&b, "- **%s** (`%s`): broken %s.%s\n", k.Rule, k.Kind, count(len(broke)), before)
		for j, x := range broke {
			if j == 20 {
				fmt.Fprintf(&b, "  - … and %d more, in the block below.\n", len(broke)-20)
				break
			}
			fmt.Fprintf(&b, "  - %s: %s\n", x.Subject, x.What)
		}
	}

	b.WriteString("\n## Counts\n| | in the window | per closed issue |\n|---|---|---|\n")
	for _, name := range []string{"conflicts", "takeovers", "person_flags", "ci_reruns", "by_hand"} {
		fmt.Fprintf(&b, "| %s | %g | %g |\n", name, c.Metrics[name], c.Metrics[name+"_per_issue"])
	}
	known := 0
	for _, r := range c.Rows {
		if r.Minutes >= 0 {
			known++
		}
	}
	fmt.Fprintf(&b, "\nClaim to merge: median %s over the %d issues whose claim and merge are both on record.\n", span(int(c.Metrics["claim_to_merge_minutes"])), known)
	boxed, filed := c.followups()
	fmt.Fprintf(&b, "\nFollow-ups: %d of the %d issues a box closed (by a land, a supersede or a close) filed one, %g%%; the rule check `followups` holds it to issues/config/followup-share.\n", filed, boxed, c.Metrics["followup_share"])

	b.WriteString("\n## Metrics against the previous retros\n")
	if len(c.History) == 0 {
		b.WriteString("This is the first retro with a report: the trend starts here.\n")
	} else {
		b.WriteString("| metric |")
		for _, h := range c.History {
			fmt.Fprintf(&b, " #%d |", h.Retro)
		}
		b.WriteString(" now | since the last |\n|---|")
		b.WriteString(strings.Repeat("---|", len(c.History)+2) + "\n")
		last := c.History[len(c.History)-1].Metrics
		for _, name := range metricNames {
			fmt.Fprintf(&b, "| %s |", name)
			for _, h := range c.History {
				if v, ok := h.Metrics[name]; ok {
					fmt.Fprintf(&b, " %g |", v)
				} else {
					b.WriteString(" – |")
				}
			}
			fmt.Fprintf(&b, " %g | %s |\n", c.Metrics[name], trend(name, last, c.Metrics))
		}
	}

	b.WriteString("\n## The previous retro\n")
	if c.Score == nil {
		b.WriteString("None: this is the first retro.\n")
	} else {
		sc := c.Score
		fmt.Fprintf(&b, "#%d found %d, of which %d became issues and %d of those closed as completed; %d recurred.\n",
			sc.Retro, sc.Findings, sc.Issues, sc.Closed, sc.Recurred)
		if len(sc.Items) > 0 {
			b.WriteString("\n| finding | class | issue | state | recurred | metric |\n|---|---|---|---|---|---|\n")
		}
		for _, it := range sc.Items {
			issue, metric := "–", "–"
			if it.Issue > 0 {
				issue = fmt.Sprintf("#%d", it.Issue)
			}
			if it.Metric != "" {
				metric = fmt.Sprintf("%s %g → %g", it.Metric, it.Before, it.Now)
			}
			fmt.Fprintf(&b, "| %s | %s | %s | %s | %v | %s |\n", it.Title, it.Class, issue, it.State, it.Recurred, metric)
		}
	}

	b.WriteString("\n## Scripts\n")
	if len(c.Scripts) == 0 {
		b.WriteString("None was added under `src/scripts/` in the window.\n")
	}
	groups := map[string][]Script{}
	var names []string
	for _, sc := range c.Scripts {
		if groups[sc.Group] == nil {
			names = append(names, sc.Group)
		}
		groups[sc.Group] = append(groups[sc.Group], sc)
	}
	sort.Strings(names)
	for _, g := range names {
		fmt.Fprintf(&b, "- **%s**\n", g)
		for _, sc := range groups[g] {
			why := sc.Why
			if why == "" {
				why = "no comment line says why"
			}
			fmt.Fprintf(&b, "  - `%s` (PR #%d): %s\n", sc.Path, sc.PR, why)
		}
	}
	return b.String()
}

// count says how often: once, 2 times.
func count(n int) string {
	if n == 1 {
		return "once"
	}
	return fmt.Sprintf("%d times", n)
}

// trend says how a metric moved since the last retro, and whether that is
// the right way.
func trend(name string, last, now Metrics) string {
	before, ok := last[name]
	switch {
	case !ok:
		return "new"
	case now[name] == before:
		return "same"
	case (now[name] < before) == lowerIsBetter(name):
		return fmt.Sprintf("better (%+g)", now[name]-before)
	}
	return fmt.Sprintf("worse (%+g)", now[name]-before)
}

// matrix is every closed issue × every landing question, a question at a time.
func (c Collected) matrix(qs []Question) string {
	var b strings.Builder
	b.WriteString("## The matrix\nEvery closed issue's landing answer, a question at a time; \"none\" answers are left out. It stays in the draft, not in the posted report.\n")
	missing := []string{}
	for _, r := range c.Rows {
		if r.Answers == nil {
			missing = append(missing, fmt.Sprintf("#%d", r.Number))
		}
	}
	if len(missing) > 0 {
		fmt.Fprintf(&b, "\nNo landing answers: %s.\n", strings.Join(missing, ", "))
	}
	for _, q := range qs {
		fmt.Fprintf(&b, "\n### `%s`: %s\n", q.Key, q.Question)
		said := 0
		for _, r := range c.Rows {
			a, ok := r.Answers[q.Key]
			if !ok || nothing(a) {
				continue
			}
			said++
			fmt.Fprintf(&b, "- #%d %s: %s\n", r.Number, r.Title, strings.ReplaceAll(strings.TrimSpace(a), "\n", "\n  "))
		}
		if said == 0 {
			b.WriteString("Nothing but none.\n")
		}
	}
	return b.String()
}

// assemble is the report as text: the judgment rendered from the block, then
// the facts, then the block.
func (r RetroReport) assemble(facts string) (string, error) {
	data, err := yaml.Marshal(r)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s\n# Retro #%d: the report\n\n%s\n%s\n%s\n%s\n\n%s\n```yaml\n%s```\n",
		reportMark, r.Retro, judgmentMark, r.judgment(), factsMark, strings.TrimSpace(facts), reportBlock, data), nil
}

// judgment renders the box's half of the report from the block.
func (r RetroReport) judgment() string {
	if len(r.Findings) == 0 && len(r.WentWell) == 0 {
		return "The box judges here: it fills `findings`, `classes` and `went_well` in the block below, and `se retro report` writes this part from them.\n"
	}
	var b strings.Builder
	b.WriteString("## Findings\n")
	for _, cl := range r.Classes {
		var in []Lesson
		for _, f := range r.Findings {
			if f.Class == cl.Name && !f.Retro {
				in = append(in, f)
			}
		}
		if len(in) == 0 {
			continue
		}
		fmt.Fprintf(&b, "\n### %s (%d)\nFix: %s\n", cl.Name, len(in), cl.Fix)
		for _, f := range in {
			b.WriteString(f.line())
		}
	}
	b.WriteString("\n## What went well\n")
	for _, w := range r.WentWell {
		fmt.Fprintf(&b, "- %s\n", w)
	}
	b.WriteString("\n## The retro itself\n")
	if r.Previous != nil {
		fmt.Fprintf(&b, "The last retro's findings: %d became issues, %d of those closed, %d recurred anyway.\n", r.Previous.Issues, r.Previous.Closed, r.Previous.Recurred)
	} else {
		b.WriteString("No retro before this one to score.\n")
	}
	proposals := 0
	for _, f := range r.Findings {
		if f.Retro {
			if proposals == 0 {
				b.WriteString("\nProposals for the retro itself:\n")
			}
			proposals++
			b.WriteString(f.line())
		}
	}
	if proposals == 0 {
		b.WriteString("No proposal to change the retro itself.\n")
	}
	return b.String()
}

func (f Lesson) line() string {
	who := "normal queue"
	if f.Controversial {
		who = "for a person: " + f.Why
	}
	s := fmt.Sprintf("- **%s** (%s; %s)", f.Title, f.Home, who)
	if f.Issue > 0 {
		s += fmt.Sprintf(": #%d", f.Issue)
	}
	return s + "\n  " + strings.ReplaceAll(strings.TrimSpace(f.Body), "\n", "\n  ") + "\n"
}

// ParseReport reads a report, a draft or a posted one, back: its block and
// its facts as text.
func ParseReport(text string) (r RetroReport, facts string, err error) {
	if !strings.Contains(text, reportMark) {
		return RetroReport{}, "", errors.New("it is no retro report: the mark " + reportMark + " is missing")
	}
	if cut, _, ok := strings.Cut(text, matrixMark); ok {
		text = cut
	}
	head, rest, ok := strings.Cut(text, reportBlock+"\n```yaml\n")
	if !ok {
		return RetroReport{}, "", errors.New("the report carries no machine-readable block under " + reportBlock)
	}
	block, _, ok := strings.Cut("\n"+rest, "\n```")
	if !ok {
		return RetroReport{}, "", errors.New("the report's block is not closed")
	}
	if err := yaml.Unmarshal([]byte(block), &r); err != nil {
		return RetroReport{}, "", fmt.Errorf("the report's block: %v", err)
	}
	if _, f, ok := strings.Cut(head, factsMark); ok {
		facts = f
	}
	return r, strings.TrimSpace(facts), nil
}

// judged refuses a report whose judgment is not complete: every finding
// needs a title, a class the classes name, a body and a home, and a reason
// where it is controversial; every class a fix; and something went well.
func (r RetroReport) judged() error {
	var why []string
	classes := map[string]bool{}
	for _, c := range r.Classes {
		if strings.TrimSpace(c.Name) == "" || strings.TrimSpace(c.Fix) == "" {
			why = append(why, fmt.Sprintf("class %q needs a name and a fix", c.Name))
		}
		classes[c.Name] = true
	}
	for k, f := range r.Findings {
		name := fmt.Sprintf("finding %d (%q)", k+1, f.Title)
		switch {
		case strings.TrimSpace(f.Title) == "" || strings.TrimSpace(f.Body) == "":
			why = append(why, name+" needs a title and a body")
		case !classes[f.Class]:
			why = append(why, fmt.Sprintf("%s names class %q, which classes does not", name, f.Class))
		case !contains(homes, f.Home):
			why = append(why, fmt.Sprintf("%s has home %q, not one of %s", name, f.Home, strings.Join(homes, ", ")))
		case f.Controversial && strings.TrimSpace(f.Why) == "":
			why = append(why, name+" is controversial without a why")
		case f.Check != "" && kindOrder(f.Check) == len(checkKinds):
			why = append(why, fmt.Sprintf("%s names check %q, which is no rule check", name, f.Check))
		case f.Metric != "" && !contains(metricNames, f.Metric):
			why = append(why, fmt.Sprintf("%s names metric %q, which is no metric", name, f.Metric))
		}
	}
	if len(r.WentWell) == 0 {
		why = append(why, "went_well is empty: record what went well")
	}
	if len(why) == 0 {
		return nil
	}
	return fmt.Errorf("the report's judgment is not complete, so nothing was written: %s", strings.Join(why, "; "))
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// postedReport is the last report posted on issue n, nil where it has none.
func (s Source) postedReport(n int) (*RetroReport, error) {
	text, err := s.lastReport(n)
	if err != nil || text == "" {
		return nil, err
	}
	r, _, err := ParseReport(text)
	if err != nil {
		return nil, fmt.Errorf("the report on #%d: %w", n, err)
	}
	return &r, nil
}

// lastReport is the text of the last report comment on issue n, and whether
// a person resumed the issue after it.
func (s Source) lastReport(n int) (string, error) {
	return s.lastPosted(n, reportMark)
}

// lastPosted is the text of the last comment on issue n that opens with mark.
func (s Source) lastPosted(n int, mark string) (string, error) {
	comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return "", err
	}
	text := ""
	for _, c := range comments {
		if strings.HasPrefix(c.Body, mark) {
			text = c.Body
		}
	}
	return text, nil
}

// Posted is the report already on retro n, posted for the owner before
// retros stopped waiting, for the box that files it; "" where there is none.
func (s Source) Posted(n int) (string, error) {
	if _, err := s.retroIssue(n); err != nil {
		return "", err
	}
	text, err := s.lastReport(n)
	return text, err
}

// Filed is what se retro report did.
type Filed struct {
	// Retro is the issue of the run filed: the retro, or the overhaul.
	Retro int `json:"retro"`
	// Issues are the issues created, Person those of them for a person.
	Issues []int `json:"issues"`
	Person []int `json:"person"`
	// Left says why the claim issue-N is still there, where its deletion was
	// refused.
	Left string `json:"left,omitempty"`
	// Ready is true where an issue it created is ready, so the routine fires.
	Ready bool `json:"-"`
}

// FileReport files retro n's report, the text of a draft the box judged: one
// issue per finding, through the same code as se issue new, one for a person
// where it is controversial; the report, with those issues, as its closing
// comment; and it closes. A retro never waits: what needs a person is in the
// issues it made. Its branch issue-n goes.
func (s Source) FileReport(n int, draft string) (Filed, error) {
	r, facts, err := ParseReport(draft)
	if err != nil {
		return Filed{}, err
	}
	if r.Retro != n {
		return Filed{}, fmt.Errorf("the report is retro #%d's, not #%d's", r.Retro, n)
	}
	if err := r.judged(); err != nil {
		return Filed{}, err
	}
	i, err := s.retroIssue(n)
	if err != nil {
		return Filed{}, err
	}
	run := filing{kind: "retro", mark: reportMark, assemble: func() (string, error) { return r.assemble(facts) }}
	run.mint = func(out *Filed) error {
		for k := range r.Findings {
			f := &r.Findings[k]
			if f.Issue > 0 {
				continue
			}
			body := fmt.Sprintf("%s\n\nFound by the retro #%d, class **%s**; the fix it asks for is a %s.", strings.TrimSpace(f.Body), n, f.Class, f.Home)
			var err error
			if f.Issue, err = s.mint(f.Title, body, f.Controversial, f.Why, out); err != nil {
				return err
			}
		}
		return nil
	}
	return s.fileRun(i, run)
}

// filing is a run (a retro, an overhaul) whose judged report is filed: its
// kind, the mark its report opens with, how its report is written, and how
// its findings become issues.
type filing struct {
	kind, mark string
	assemble   func() (string, error)
	mint       func(out *Filed) error
}

// fileRun files run's report on its issue i: its findings become issues, the
// report, with their issues, is its closing comment, and it closes. A run
// never waits for a person: its controversial findings are issues for one.
// Its claim issue-N goes.
func (s Source) fileRun(i issue, run filing) (Filed, error) {
	n := i.Number
	out := Filed{Retro: n, Issues: []int{}, Person: []int{}}
	if err := run.mint(&out); err != nil {
		return out, err
	}
	text, err := run.assemble()
	if err != nil {
		return out, err
	}
	if err := s.postReport(n, text); err != nil {
		return out, err
	}
	if _, err := s.GitHub.Send("PATCH", fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), github.F("state", "closed"), github.F("state_reason", "completed")); err != nil {
		return out, fmt.Errorf("closing the %s #%d: %w", run.kind, n, err)
	}
	out.Left = s.dropBranch(n, run.kind)
	return out, nil
}

// mint creates one finding's issue through the same code as se issue new: a
// controversial one for a person (ForPerson), the rest in the normal queue.
// It records the issue in out.
func (s Source) mint(title, body string, controversial bool, why string, out *Filed) (int, error) {
	if controversial {
		made, err := s.ForPerson(title, "Controversial, so it waits for a person: "+why+"\n\n"+body, 0, nil)
		if made.Number > 0 {
			out.Issues = append(out.Issues, made.Number)
			out.Person = append(out.Person, made.Number)
		}
		return made.Number, err
	}
	made, ready, err := s.create(title, body, 0, nil, []string{Label})
	if err != nil {
		return 0, err
	}
	out.Issues = append(out.Issues, made.Number)
	out.Ready = out.Ready || ready
	return made.Number, nil
}

// postReport posts text, a report, on issue n.
func (s Source) postReport(n int, text string) error {
	if _, err := s.GitHub.Send("POST", fmt.Sprintf("repos/%s/issues/%d/comments", s.Repo, n), github.F("body", text)); err != nil {
		return fmt.Errorf("posting the report on #%d: %w", n, err)
	}
	return nil
}

// dropBranch deletes the claim issue-n, where it exists: a retro lands no
// branch. It never fails the report: where the deletion is refused (a box's
// token may not delete branches), it answers why the branch stays and what
// removes it.
func (s Source) dropBranch(n int, kind string) string {
	_, err := s.GitHub.Send("DELETE", fmt.Sprintf("repos/%s/git/refs/heads/%s", s.Repo, Branch(n)))
	if err == nil || github.Status(err) == 422 || github.Status(err) == 404 {
		return ""
	}
	return fmt.Sprintf("%s stays (%v): se fleet prune removes it once the %s is closed, and a resumed %s's stale claim is taken over", Branch(n), err, kind, kind)
}
