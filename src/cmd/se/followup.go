package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/mb-89/SE/src/internal/guidance"
	"github.com/mb-89/SE/src/internal/issues"
)

// The owner's rule: a box writes to GitHub once, at the end of its work, and
// files at most issues/config/max-followups issues. So se issue new in a box
// queues the issue in the workspace, and the land, supersede or close that
// ends the box's issue files it after its own work, marked as that issue's
// follow-up so the retro counts it.

// newIssue is an se issue new as its flags give it: what a box queues, and
// what se issue new, or the land after it, creates.
type newIssue struct {
	Title string `json:"title"`
	// Body is the body as given, before the skills line.
	Body           string   `json:"body"`
	BlockedBy      []int    `json:"blocked_by"`
	Parent         int      `json:"parent,omitempty"`
	Blocks         []int    `json:"blocks,omitempty"`
	Review         bool     `json:"review,omitempty"`
	Final          bool     `json:"final,omitempty"`
	Person         bool     `json:"person,omitempty"`
	AllowDuplicate bool     `json:"allow_duplicate,omitempty"`
	Skills         []string `json:"skills,omitempty"`
}

// newAnswer is what se issue new --json answers for an issue it created.
type newAnswer struct {
	Number    int    `json:"number"`
	URL       string `json:"url"`
	BlockedBy []int  `json:"blocked_by"`
	Parent    int    `json:"parent,omitempty"`
	Blocks    []int  `json:"blocks,omitempty"`
	Review    bool   `json:"review,omitempty"`
	Final     bool   `json:"final,omitempty"`
	Person    bool   `json:"person,omitempty"`
	Fanout    string `json:"fanout,omitempty"`
}

// refused is what se issue new refuses on GitHub before it creates
// anything: a title an open se issue under the same parent has already,
// unless a duplicate is allowed, and a --blocks number that is no issue.
func (n newIssue) refused(s issues.Source) error {
	if n.AllowDuplicate {
		if err := s.CloseParents(); err != nil {
			return err
		}
	} else if dup, err := s.Duplicate(n.Title, n.Parent); err != nil {
		return err
	} else if dup > 0 {
		where := "at the top"
		if n.Parent > 0 {
			where = fmt.Sprintf("a sub-issue of #%d", n.Parent)
		}
		return fmt.Errorf("#%d is an open se issue titled %q, %s, already; --allow-duplicate creates another", dup, strings.TrimSpace(n.Title), where)
	}
	return s.Exist(n.Blocks)
}

// create creates the issue, its links and its labels, as se issue new does;
// where of is above zero, as the follow-up of the box's issue #of, its body
// marked so. Call refused first.
func (n newIssue) create(s issues.Source, of int) (made issues.Issue, ready bool, err error) {
	body := guidance.With(n.Body, n.Skills)
	if of > 0 {
		body = issues.AsFollowup(body, of)
	}
	if n.Person {
		made, err = s.ForPerson(n.Title, body, n.Parent, n.BlockedBy)
	} else {
		var labels []string
		if n.Review {
			labels = append(labels, issues.ReviewLabel)
		}
		if n.Final {
			labels = append(labels, issues.FinalLabel)
		}
		made, ready, err = s.Create(n.Title, body, n.Parent, n.BlockedBy, labels...)
	}
	if err != nil {
		return made, false, err
	}
	return made, ready, s.Blocking(made, n.Blocks)
}

func (n newIssue) answer(made issues.Issue, fanout string) newAnswer {
	return newAnswer{made.Number, made.URL, append([]int{}, n.BlockedBy...), n.Parent, n.Blocks, n.Review, n.Final, n.Person, fanout}
}

// text says what was created: head, then its URL and its links.
func (n newIssue) text(head string, made issues.Issue) string {
	text := head + "\n" + made.URL
	if n.Parent > 0 {
		text += fmt.Sprintf("\nA sub-issue of #%d.", n.Parent)
	}
	if n.Review {
		text += "\nLabelled " + issues.ReviewLabel + ": it is reviewed once its sub-issues have closed."
	}
	if len(n.Blocks) > 0 {
		text += "\nIt blocks " + numbers(n.Blocks) + "."
	}
	if n.Person {
		text += "\nFor a person: labelled " + issues.PersonLabel + " and assigned to the owner."
	}
	if n.Final {
		text += "\nLabelled " + issues.FinalLabel + ": its last attempt, never superseded again."
	}
	if len(n.BlockedBy) > 0 {
		names := make([]string, len(n.BlockedBy))
		for k, b := range n.BlockedBy {
			names[k] = "#" + strconv.Itoa(b)
		}
		text += "\nBlocked by " + strings.Join(names, ", ") + "."
	}
	return text
}

func queuePath(c *Call) string { return filepath.Join(c.Paths().Runtime(), "followups.json") }

// readQueued answers the issues the box queued, oldest first; none where
// nothing is queued.
func readQueued(c *Call) ([]newIssue, error) {
	data, err := c.Disk.ReadFile(queuePath(c))
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var q []newIssue
	if err := json.Unmarshal(data, &q); err != nil {
		return nil, fmt.Errorf("the issues this box queued, %s: %v", queuePath(c), err)
	}
	return q, nil
}

// writeQueued keeps q as the box's queue; an empty q clears it.
func writeQueued(c *Call, q []newIssue) error {
	if len(q) == 0 {
		if err := c.Disk.Remove(queuePath(c)); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		return nil
	}
	if err := c.Disk.MkdirAll(c.Paths().Runtime()); err != nil {
		return err
	}
	data, err := json.Marshal(q)
	if err != nil {
		return err
	}
	return c.Disk.Replace(queuePath(c), data)
}

// queue is se issue new in a box: it records n for the land, supersede or
// close that ends the box's issue, writing nothing to GitHub. It refuses one
// past issues/config/max-followups; replace puts n in place of the last
// queued.
func queue(c *Call, n newIssue, replace, asJSON bool) (Reply, error) {
	q, err := readQueued(c)
	if err != nil {
		return Reply{}, err
	}
	most := issueConfig().MaxFollowups
	replaced := ""
	switch {
	case replace && len(q) > 0:
		replaced = q[len(q)-1].Title
		q[len(q)-1] = n
	case len(q) >= most && most > 0:
		return Reply{}, fmt.Errorf("a box files at most %s (issues/config/max-followups), and %q is queued already: fold both into one and pass --replace to replace the queued one, or, where what is left is too big for one issue, make the one issue --person", plural(most, "issue"), q[len(q)-1].Title)
	case len(q) >= most:
		return Reply{}, fmt.Errorf("a box files no issue: issues/config/max-followups is 0")
	default:
		q = append(q, n)
	}
	if err := writeQueued(c, q); err != nil {
		return Reply{}, err
	}
	if asJSON {
		data, err := json.Marshal(struct {
			Queued   bool   `json:"queued"`
			Title    string `json:"title"`
			Replaced string `json:"replaced,omitempty"`
			Queue    string `json:"queue"`
		}{true, n.Title, replaced, queuePath(c)})
		return Reply{Text: string(data)}, err
	}
	text := fmt.Sprintf("Queued %q, not created: a box writes to GitHub once, at its end, so the se issue land, se issue supersede or se issue close --fixed-by of the issue it took files it, as se issue new would create it, and names it.", n.Title)
	if replaced != "" {
		text = fmt.Sprintf("Queued %q in place of %q, not created: a box writes to GitHub once, at its end, so the se issue land, se issue supersede or se issue close --fixed-by of the issue it took files it, as se issue new would create it, and names it.", n.Title, replaced)
	}
	return Reply{Text: text + fmt.Sprintf("\nA box files at most %s (issues/config/max-followups): fold what else is left into it with se issue new --replace, or, where that is too big for one issue, make it --person.", plural(most, "issue"))}, nil
}

func plural(n int, word string) string {
	if n == 1 {
		return "one " + word
	}
	return fmt.Sprintf("%d %ss", n, word)
}

// queued answers the issues the box queued, and refuses, before the land,
// supersede or close does its own work, one that se issue new would refuse,
// so a land never leaves a follow-up it cannot file.
func queued(c *Call, s issues.Source) ([]newIssue, error) {
	q, err := readQueued(c)
	if err != nil {
		return nil, err
	}
	for _, n := range q {
		linked := append([]int{}, n.BlockedBy...)
		if n.Parent > 0 {
			linked = append(linked, n.Parent)
		}
		if err == nil {
			err = n.refused(s)
		}
		if err == nil {
			err = s.Exist(linked)
		}
		if err != nil {
			return nil, fmt.Errorf("the issue this box queued, %q, would be refused, so nothing was done: %w; fix it with se issue new --replace", n.Title, err)
		}
	}
	return q, nil
}

// filed is a queued issue the land, supersede or close filed.
type filed struct {
	newIssue
	made issues.Issue
}

// fileQueued files q, the follow-ups of the box's issue #of, after the
// command's own work succeeded, and clears the queue; what it could not file
// stays queued. ready says whether one of them is ready, so the routine fires.
func fileQueued(c *Call, s issues.Source, of int, q []newIssue) (out []filed, ready bool, err error) {
	for k, n := range q {
		made, r, err := n.create(s, of)
		ready = ready || r
		// One created, if only in part, is filed: queued again, it would be twice.
		left := q[k:]
		if made.Number > 0 {
			out, left = append(out, filed{n, made}), q[k+1:]
		}
		if err != nil {
			if werr := writeQueued(c, left); werr != nil {
				err = fmt.Errorf("%w; and keeping the queue: %v", err, werr)
			}
			return out, ready, fmt.Errorf("filing the issue this box queued, %q: %w", n.Title, err)
		}
	}
	return out, ready, writeQueued(c, nil)
}

// filedText says what fileQueued filed, after the command's own lines.
func filedText(of int, fs []filed) string {
	text := ""
	for _, f := range fs {
		text += "\n\n" + f.text(fmt.Sprintf("Filed the queued follow-up of #%d: #%d %s", of, f.made.Number, f.made.Title), f.made)
	}
	return text
}

// filedAnswers is fileQueued's issues as se issue new --json answers them.
func filedAnswers(fs []filed) []newAnswer {
	var out []newAnswer
	for _, f := range fs {
		out = append(out, f.answer(f.made, ""))
	}
	return out
}

// closeOut ends a land, a supersede or a close of issue of: it files what the
// box queued (q, which queued checked), and adds what it filed to r, the
// command's own answer, text or --json. fire fires the routine where a filed
// issue is ready, or the command's own work made one ready (own), once.
func closeOut(c *Call, s issues.Source, of int, q []newIssue, asJSON bool, own bool, fire func() string, r func(filed []newAnswer, fanout string) (Reply, error)) (Reply, error) {
	fs, ready, ferr := fileQueued(c, s, of, q)
	fanout := ""
	if ready || own {
		fanout = fire()
	}
	reply, err := r(filedAnswers(fs), fanout)
	if err != nil {
		return reply, err
	}
	if !asJSON {
		reply.Text += filedText(of, fs)
	}
	if ferr != nil {
		return Reply{}, fmt.Errorf("%s\n\nbut %w; it stays queued, and the next se issue land, supersede or close files it", reply.Text, ferr)
	}
	return reply, nil
}
