package issues

import (
	"encoding/base64"
	"fmt"
	"regexp"
	"strings"
)

// PrinciplesPath is the file of the product's principles a reviewer judges
// against, beside the ask.
const PrinciplesPath = "spec/principles.md"

// Brief is everything a reviewer of a gate starts from, read by one command
// so nothing is skipped or slanted. The workers' own accounts of their work
// (their PR descriptions and comments) are withheld: they are given only once
// the findings are verified, as Claims.
type Brief struct {
	// Gate is the issue under review: its text is the question.
	Gate BriefIssue `json:"gate"`
	// Tree is every issue below the gate, open or closed, at any depth,
	// parents before their sub-issues: the ask and its acceptance criteria.
	Tree []BriefIssue `json:"tree"`
	// Commit is main's head when the brief was read: the merged code reviewed.
	Commit string `json:"commit"`
	// CI is the check runs on Commit.
	CI []Check `json:"ci"`
	// Principles is spec/principles.md at Commit; empty where there is none.
	Principles string `json:"principles"`
	// Rereview is set where the gate's last review failed.
	Rereview *Rereview `json:"rereview,omitempty"`
	// Claims are the workers' accounts, given with --claims only.
	Claims []Account `json:"claims,omitempty"`
}

// BriefIssue is one issue of the brief's tree.
type BriefIssue struct {
	Number int    `json:"number"`
	Title  string `json:"title"`
	Body   string `json:"body"`
	State  string `json:"state"`
	Reason string `json:"state_reason,omitempty"`
	// Above is the issue it is a sub-issue of; 0 for the gate.
	Above int `json:"above,omitempty"`
}

// Check is one CI check run.
type Check struct {
	Name       string `json:"name"`
	Status     string `json:"status"`
	Conclusion string `json:"conclusion"`
	URL        string `json:"html_url"`
}

// Rereview is what a re-review is limited to: the earlier blockers, and the
// code changed since the review that found them.
type Rereview struct {
	Since    string `json:"since"`
	Blockers []int  `json:"blockers"`
	Diff     string `json:"diff"`
}

// Account is a worker's account of a leaf: its merged PR's description and the
// leaf's comments. Accounts are checked, never taken as evidence.
type Account struct {
	Issue    int      `json:"issue"`
	PR       int      `json:"pr,omitempty"`
	URL      string   `json:"url,omitempty"`
	Body     string   `json:"body,omitempty"`
	Comments []string `json:"comments,omitempty"`
}

// Brief reads gate n's brief. With claims it adds the workers' accounts,
// which the reviewer reads only after its findings are verified.
func (s Source) Brief(n int, claims bool) (Brief, error) {
	got, err := api[struct {
		issue
		Reason string `json:"state_reason"`
	}](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, n), false)
	if err != nil {
		return Brief{}, err
	}
	g := got[0]
	if g.PullRequest != nil {
		return Brief{}, fmt.Errorf("#%d is a pull request, not an issue", n)
	}
	b := Brief{Gate: BriefIssue{Number: g.Number, Title: g.Title, Body: g.Body, State: g.State, Reason: g.Reason}, Tree: []BriefIssue{}, CI: []Check{}}
	if err := s.briefTree(n, &b.Tree); err != nil {
		return Brief{}, err
	}
	head, err := api[struct {
		SHA string `json:"sha"`
	}](s, fmt.Sprintf("repos/%s/commits/main", s.Repo), false)
	if err != nil {
		return Brief{}, err
	}
	b.Commit = head[0].SHA
	runs, err := api[struct {
		Runs []Check `json:"check_runs"`
	}](s, fmt.Sprintf("repos/%s/commits/%s/check-runs?per_page=100", s.Repo, b.Commit), false)
	if err != nil {
		return Brief{}, err
	}
	b.CI = append(b.CI, runs[0].Runs...)
	if b.Principles, err = s.file(PrinciplesPath, b.Commit); err != nil {
		return Brief{}, err
	}
	last, err := s.lastVerdict(n)
	if err != nil {
		return Brief{}, err
	}
	if last.failed() {
		b.Rereview = &Rereview{Since: last.Report.Commit, Blockers: last.blockers(), Diff: fmt.Sprintf("git diff %s..%s", last.Report.Commit, b.Commit)}
	}
	if claims {
		if b.Claims, err = s.claims(b.Tree); err != nil {
			return Brief{}, err
		}
	}
	return b, nil
}

// briefTree appends every issue below n, open or closed, at any depth.
func (s Source) briefTree(n int, out *[]BriefIssue) error {
	subs, err := api[struct {
		issue
		Reason string `json:"state_reason"`
	}](s, fmt.Sprintf("repos/%s/issues/%d/sub_issues?per_page=100", s.Repo, n), true)
	if err != nil {
		return err
	}
	for _, c := range subs {
		*out = append(*out, BriefIssue{Number: c.Number, Title: c.Title, Body: c.Body, State: c.State, Reason: c.Reason, Above: n})
		if c.SubIssues != nil && c.SubIssues.Total > 0 {
			if err := s.briefTree(c.Number, out); err != nil {
				return err
			}
		}
	}
	return nil
}

// file reads path at commit; empty where it does not exist there.
func (s Source) file(path, commit string) (string, error) {
	got, err := api[struct {
		Content  string `json:"content"`
		Encoding string `json:"encoding"`
	}](s, fmt.Sprintf("repos/%s/contents/%s?ref=%s", s.Repo, path, commit), false)
	if err != nil {
		if strings.Contains(err.Error(), "HTTP 404") {
			return "", nil
		}
		return "", err
	}
	if got[0].Encoding != "base64" {
		return got[0].Content, nil
	}
	data, err := base64.StdEncoding.DecodeString(strings.ReplaceAll(got[0].Content, "\n", ""))
	if err != nil {
		return "", fmt.Errorf("reading %s at %s: %w", path, commit, err)
	}
	return string(data), nil
}

// htmlComment is a mark se leaves in a comment, which is no part of its account.
var htmlComment = regexp.MustCompile(`(?s)<!--.*?-->`)

// claims reads the workers' accounts of the tree's closed leaves: each one's
// merged PR, from its branch issue-<n>, and its comments.
func (s Source) claims(tree []BriefIssue) ([]Account, error) {
	pulls, err := api[struct {
		Number int     `json:"number"`
		URL    string  `json:"html_url"`
		Body   string  `json:"body"`
		Merged *string `json:"merged_at"`
		Head   struct {
			Ref string `json:"ref"`
		} `json:"head"`
	}](s, fmt.Sprintf("repos/%s/pulls?state=closed&base=main&per_page=100", s.Repo), true)
	if err != nil {
		return nil, err
	}
	parents := map[int]bool{}
	for _, i := range tree {
		parents[i.Above] = true
	}
	out := []Account{}
	for _, i := range tree {
		if parents[i.Number] || i.State != "closed" {
			continue
		}
		c := Account{Issue: i.Number}
		for _, p := range pulls {
			if p.Head.Ref == Branch(i.Number) && p.Merged != nil {
				c.PR, c.URL, c.Body = p.Number, p.URL, p.Body
			}
		}
		comments, err := api[comment](s, fmt.Sprintf("repos/%s/issues/%d/comments?per_page=100", s.Repo, i.Number), true)
		if err != nil {
			return nil, err
		}
		for _, m := range comments {
			if body := strings.TrimSpace(htmlComment.ReplaceAllString(m.Body, "")); body != "" {
				c.Comments = append(c.Comments, body)
			}
		}
		out = append(out, c)
	}
	return out, nil
}

// quote sets a text another wrote apart as a Markdown quote, so its headings
// stay inside it.
func quote(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return "> (empty)"
	}
	lines := strings.Split(text, "\n")
	for k, l := range lines {
		lines[k] = strings.TrimRight("> "+l, " ")
	}
	return strings.Join(lines, "\n")
}

// Text is the brief as a reviewer reads it.
func (b Brief) Text() string {
	var w strings.Builder
	fmt.Fprintf(&w, "# Brief for the review of #%d %s\n\n", b.Gate.Number, b.Gate.Title)
	fmt.Fprintf(&w, "Review the merged code at %s, main's head now: `git checkout --detach %s`.\n", b.Commit, b.Commit)
	if r := b.Rereview; r != nil {
		fmt.Fprintf(&w, "\nThis is a re-review: the review at %s failed. Check only the earlier blockers, %s, and the code changed since: `%s`. Raise no new non-blocking finding.\n",
			r.Since, hashes(r.Blockers), r.Diff)
	}
	fmt.Fprintf(&w, "\n## The question: #%d %s (%s)\n\n%s\n", b.Gate.Number, b.Gate.Title, b.Gate.State, quote(b.Gate.Body))
	fmt.Fprintf(&w, "\n## Its tree\n")
	if len(b.Tree) == 0 {
		w.WriteString("\nNo sub-issues.\n")
	}
	for _, i := range b.Tree {
		state := i.State
		if i.Reason != "" {
			state += ", " + i.Reason
		}
		fmt.Fprintf(&w, "\n### #%d %s (%s, under #%d)\n\n%s\n", i.Number, i.Title, state, i.Above, quote(i.Body))
	}
	fmt.Fprintf(&w, "\n## CI at %s\n\n", b.Commit)
	if len(b.CI) == 0 {
		w.WriteString("No check runs.\n")
	}
	for _, c := range b.CI {
		fmt.Fprintf(&w, "- %s: %s %s\n", c.Name, c.Status, c.Conclusion)
	}
	fmt.Fprintf(&w, "\n## %s\n\n", PrinciplesPath)
	if strings.TrimSpace(b.Principles) == "" {
		fmt.Fprintf(&w, "There is no %s at %s: judge against the ask alone.\n", PrinciplesPath, b.Commit)
	} else {
		w.WriteString(strings.TrimSpace(b.Principles) + "\n")
	}
	if b.Claims == nil {
		w.WriteString("\n## Withheld\n\nThe workers' PR descriptions and comments are withheld until your findings are verified: then `--claims` shows them, as claims to check, never as evidence.\n")
		return w.String()
	}
	w.WriteString("\n## Claims to check, never evidence\n")
	for _, c := range b.Claims {
		fmt.Fprintf(&w, "\n### #%d\n", c.Issue)
		if c.PR != 0 {
			fmt.Fprintf(&w, "\nPR #%d %s says:\n\n%s\n", c.PR, c.URL, quote(c.Body))
		}
		for _, m := range c.Comments {
			fmt.Fprintf(&w, "\nA comment says:\n\n%s\n", quote(m))
		}
	}
	return w.String()
}
