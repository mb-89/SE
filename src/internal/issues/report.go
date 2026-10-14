package issues

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// MaxFiled is the built-in value of issues/config/max-filed: how many non-blocking findings one review files as issues; the
// rest are counted, not filed, since more findings means more noise.
const MaxFiled = 5

// Report is what a reviewer hands se issue review, as JSON: the rules it
// follows are spec/review.md's.
type Report struct {
	// Commit is the pinned commit the review read, as the brief named it.
	Commit string `json:"commit"`
	// Requirements is what the ask requires, in the reviewer's words, each
	// with its evidence.
	Requirements []Requirement `json:"requirements"`
	// Findings are the verified findings, each judged blocking or not.
	Findings []ReviewFinding `json:"findings"`
	// Clean is what was examined and found sound, so a rubber-stamp shows.
	Clean []string `json:"clean"`
}

// Requirement is one thing the ask requires.
type Requirement struct {
	Item string `json:"item"`
	// Evidence is a file and line, or a command and its output.
	Evidence string `json:"evidence"`
	// Blocker is, in a re-review, the earlier blocker this item checks.
	Blocker int `json:"blocker,omitempty"`
}

// ReviewFinding is one verified finding of a review.
type ReviewFinding struct {
	Title string `json:"title"`
	// Evidence is a file and line, or a command and its output.
	Evidence string `json:"evidence"`
	// Blocking says whether letting the work through does damage; Why is
	// the judgment.
	Blocking bool   `json:"blocking"`
	Why      string `json:"why"`
	// Repeats is, in a re-review, the earlier blocker whose problem this
	// finding shows again: that final issue failed, and the gate goes to a
	// person.
	Repeats int `json:"repeats,omitempty"`
	// Issue is the issue se filed for it; 0 where it was not filed.
	Issue int `json:"issue,omitempty"`
}

// check refuses a report that breaks the rules, before anything is written.
// earlier is the blockers of the review before, where that one failed: this
// is then a re-review.
func (r Report) check(pass bool, earlier []int) error {
	if strings.TrimSpace(r.Commit) == "" {
		return fmt.Errorf("the report names no commit: give the one se review brief pinned")
	}
	if len(r.Clean) == 0 {
		return fmt.Errorf("the report has no \"checked and clean\" list: name what was examined and found sound")
	}
	for _, c := range r.Clean {
		if strings.TrimSpace(c) == "" {
			return fmt.Errorf("an entry of the \"checked and clean\" list is empty")
		}
	}
	if len(r.Requirements) == 0 {
		return fmt.Errorf("the report names no requirement: restate what the ask requires")
	}
	blocking := 0
	for _, f := range r.Findings {
		switch {
		case strings.TrimSpace(f.Title) == "":
			return fmt.Errorf("a finding needs a title")
		case strings.TrimSpace(f.Evidence) == "":
			return fmt.Errorf("finding %q has no evidence: a verified finding has a file and line, or a command and its output; drop what is unproven", f.Title)
		case strings.TrimSpace(f.Why) == "":
			return fmt.Errorf("finding %q has no judgment: say why it blocks, or why it does not", f.Title)
		case f.Repeats > 0 && !f.Blocking:
			return fmt.Errorf("finding %q repeats #%d, so it blocks", f.Title, f.Repeats)
		}
		if f.Blocking {
			blocking++
		}
	}
	for _, q := range r.Requirements {
		switch {
		case strings.TrimSpace(q.Item) == "":
			return fmt.Errorf("a requirement needs its item")
		case pass && strings.TrimSpace(q.Evidence) == "":
			return fmt.Errorf("requirement %q has no evidence, and a pass needs evidence for every requirement", q.Item)
		}
	}
	switch {
	case pass && blocking > 0:
		return fmt.Errorf("a pass has no blocking finding; this report has %d", blocking)
	case !pass && blocking == 0:
		return fmt.Errorf("a fail needs a verified blocking finding; this report has none, so it passes")
	}
	was := map[int]bool{}
	for _, b := range earlier {
		was[b] = true
	}
	checked := map[int]bool{}
	for _, q := range r.Requirements {
		switch {
		case q.Blocker == 0 && len(earlier) > 0:
			return fmt.Errorf("a re-review checks only the earlier blockers (%s): requirement %q names none", hashes(earlier), q.Item)
		case q.Blocker != 0 && !was[q.Blocker]:
			return fmt.Errorf("requirement %q names #%d, which is no earlier blocker", q.Item, q.Blocker)
		}
		checked[q.Blocker] = true
	}
	for _, b := range earlier {
		if !checked[b] {
			return fmt.Errorf("a re-review checks every earlier blocker, and no requirement checks #%d", b)
		}
	}
	for _, f := range r.Findings {
		switch {
		case len(earlier) > 0 && !f.Blocking:
			return fmt.Errorf("a re-review raises no new non-blocking finding, and %q is one", f.Title)
		case f.Repeats != 0 && !was[f.Repeats]:
			return fmt.Errorf("finding %q repeats #%d, which is no earlier blocker", f.Title, f.Repeats)
		}
	}
	return nil
}

func hashes(ns []int) string {
	out := make([]string, len(ns))
	for k, n := range ns {
		out[k] = fmt.Sprintf("#%d", n)
	}
	return strings.Join(out, ", ")
}

// body is the text of the issue a finding becomes.
func (f ReviewFinding) body(gate int) string {
	judged := "Not blocking: the review of #%d passes over it, and it is an open point."
	if f.Blocking {
		judged = "Blocking: the review of #%d waits for it, as a sub-issue of it."
	}
	return fmt.Sprintf(judged+"\n\n**Evidence:** %s\n\n**Judgment:** %s\n\nLabelled %s: filed by a review, this is its final attempt; if it fails again, it goes to a person.",
		gate, f.Evidence, f.Why, FinalLabel)
}

// Verdict is the machine-readable block a review posts on its gate,
// <!-- se:review {...} -->, so the next review of it reads what this one found.
type Verdict struct {
	Passed bool `json:"passed"`
	// Rereview is set where the review before had failed.
	Rereview bool `json:"rereview"`
	// Unfiled counts the non-blocking findings past the cap, issues/config/max-filed.
	Unfiled int    `json:"unfiled"`
	Report  Report `json:"report"`
}

var verdictMark = regexp.MustCompile(`<!-- se:review (\{.*\}) -->`)

// blockers is the issues the verdict's blocking findings became, or showed
// again; none where it passed, or is missing.
func (v *Verdict) blockers() []int {
	if !v.failed() {
		return nil
	}
	var out []int
	for _, f := range v.Report.Findings {
		if f.Blocking && f.Issue != 0 {
			out = append(out, f.Issue)
		}
		if f.Repeats != 0 {
			out = append(out, f.Repeats)
		}
	}
	sort.Ints(out)
	return out
}

func (v *Verdict) failed() bool { return v != nil && !v.Passed }

// lastVerdict reads the last review report on gate n; nil where it has none.
func (s Source) lastVerdict(n int) (*Verdict, error) {
	all, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, n), true)
	if err != nil {
		return nil, err
	}
	var last *Verdict
	for _, c := range all {
		for _, m := range verdictMark.FindAllStringSubmatch(c.Body, -1) {
			var v Verdict
			if json.Unmarshal([]byte(m[1]), &v) == nil {
				last = &v
			}
		}
	}
	return last, nil
}

// render is the report as it is posted on the gate: what a person reads,
// then the machine-readable block.
func (v Verdict) render(by Worker, maxFiled int) string {
	var b strings.Builder
	word := "FAIL"
	if v.Passed {
		word = "PASS"
	}
	kind := "Review"
	if v.Rereview {
		kind = "Re-review"
	}
	fmt.Fprintf(&b, "## %s: %s\n\nBy %s, at %s.\n\n### What the ask requires\n", kind, word, by, v.Report.Commit)
	for _, q := range v.Report.Requirements {
		item := q.Item
		if q.Blocker != 0 {
			item = fmt.Sprintf("#%d: %s", q.Blocker, item)
		}
		ev := q.Evidence
		if strings.TrimSpace(ev) == "" {
			ev = "_no evidence_"
		}
		fmt.Fprintf(&b, "- %s\n  Evidence: %s\n", item, ev)
	}
	b.WriteString("\n### Findings\n")
	if len(v.Report.Findings) == 0 {
		b.WriteString("None.\n")
	}
	for _, f := range v.Report.Findings {
		judged := "not blocking"
		if f.Blocking {
			judged = "blocking"
		}
		became := fmt.Sprintf("not filed (past the first %d)", maxFiled)
		switch {
		case f.Repeats != 0:
			became = fmt.Sprintf("repeats #%d, so this goes to a person", f.Repeats)
		case f.Issue != 0:
			became = fmt.Sprintf("#%d", f.Issue)
		}
		fmt.Fprintf(&b, "- **%s** (%s, %s)\n  Evidence: %s\n  Judgment: %s\n", f.Title, judged, became, f.Evidence, f.Why)
	}
	if v.Unfiled > 0 {
		fmt.Fprintf(&b, "\n%d more non-blocking finding(s) counted, not filed.\n", v.Unfiled)
	}
	b.WriteString("\n### Checked and clean\n")
	for _, c := range v.Report.Clean {
		fmt.Fprintf(&b, "- %s\n", c)
	}
	// json.Marshal escapes < and >, so the block cannot end early.
	data, _ := json.Marshal(v)
	fmt.Fprintf(&b, "\n<!-- se:review %s -->", data)
	return b.String()
}
