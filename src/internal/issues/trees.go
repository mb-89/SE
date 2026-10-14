package issues

import (
	"fmt"
	"strings"
)

// Node is an se issue in a tree listing: its state, how deep below the root
// it stands, and, for a parent, how many of its sub-issues are closed.
type Node struct {
	Number int      `json:"number"`
	Title  string   `json:"title"`
	State  string   `json:"state"`
	URL    string   `json:"url"`
	Labels []string `json:"labels"`
	Depth  int      `json:"depth"`
	Closed int      `json:"closed"`
	Total  int      `json:"total"`
	// Why says where an open issue stands: ready, claimed, blocked and by
	// what; empty where it was not judged.
	Why string `json:"why,omitempty"`
}

func nodeOf(i issue, depth int) Node {
	n := Node{Number: i.Number, Title: i.Title, State: i.State, URL: i.URL, Labels: []string{}, Depth: depth}
	for _, l := range i.Labels {
		n.Labels = append(n.Labels, l.Name)
	}
	if i.SubIssues != nil {
		n.Closed, n.Total = i.SubIssues.Completed, i.SubIssues.Total
	}
	return n
}

// Line is the node as one line: number, state, where an open one stands, the
// closed count of a parent, its labels and its title.
func (n Node) Line() string {
	parts := []string{fmt.Sprintf("#%d", n.Number), n.State}
	if n.Why != "" {
		parts = append(parts, n.Why)
	}
	if n.Total > 0 {
		parts = append(parts, fmt.Sprintf("%d/%d closed", n.Closed, n.Total))
	}
	if len(n.Labels) > 0 {
		parts = append(parts, strings.Join(n.Labels, ","))
	}
	return strings.Repeat("  ", n.Depth) + strings.Join(append(parts, n.Title), "  ")
}

// TreeOf lists root and every issue below it, open or closed, at any depth,
// each after its parent.
func (s Source) TreeOf(root int) ([]Node, error) {
	got, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d", s.Repo, root), false)
	if err != nil {
		return nil, err
	}
	r := got[0]
	if r.PullRequest != nil || !r.labelled(Label) {
		return nil, fmt.Errorf("#%d is not an issue labelled %s", root, Label)
	}
	out := []Node{nodeOf(r, 0)}
	var below func(n, depth int) error
	below = func(n, depth int) error {
		subs, err := api[issue](s, fmt.Sprintf("repos/%s/issues/%d/sub_issues?per_page=100", s.Repo, n), true)
		if err != nil {
			return err
		}
		for _, c := range subs {
			out = append(out, nodeOf(c, depth))
			if c.SubIssues != nil && c.SubIssues.Total > 0 {
				if err := below(c.Number, depth+1); err != nil {
					return err
				}
			}
		}
		return nil
	}
	if r.SubIssues != nil && r.SubIssues.Total > 0 {
		if err := below(root, 1); err != nil {
			return nil, err
		}
	}
	return out, nil
}
