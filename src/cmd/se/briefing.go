package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/issues"
)

func init() {
	register(Command{
		Name:    "briefing",
		Usage:   "briefing [--since TIME | --last N] [--json] [--repo OWNER/NAME]",
		Group:   "Fleet",
		Summary: "where SE stands: what waits on you, in flight, happened, next",
		Details: "read GitHub and the checkout and tell, pending first: every se-person issue with its reason and what it holds up, and every report waiting for the owner, from every registered pending source; the claimed issues and their PRs, and what fleet check reports; the issues closed in the window, each with its PR and landing answer done, and the last retro; what issue pull would take, how many issues are ready, claimed, blocked or in trees, and the queue's size with when its last issue is estimated to close (issue tree tells the detail); and what SE is. The window is the last day or the last 10 closed issues, whichever are more; --since takes a time (RFC 3339, a date, or an age such as 36h or 3d), --last a count. The skill se:briefing presents it.",
		Session: true,
		Run: func(c *Call) (Reply, error) {
			fs, src, asJSON := issueFlags(c, "briefing")
			since := fs.String("since", "", "tell of the issues closed since `TIME`: RFC 3339, a date, or an age such as 36h or 3d")
			last := fs.Int("last", 0, "tell of the last `N` closed issues")
			if err := c.Parse(fs); err != nil {
				return Reply{}, err
			}
			var w issues.Window
			switch {
			case *since != "" && *last != 0:
				return Reply{}, errors.New("briefing takes --since or --last, not both")
			case *last < 0:
				return Reply{}, errors.New("--last takes a count above zero")
			case *since != "":
				t, err := parseSince(*since, c.Clock.Now())
				if err != nil {
					return Reply{}, err
				}
				w.Since = t
			}
			w.Last = *last
			s, err := src()
			if err != nil {
				return Reply{}, err
			}
			b, err := s.Briefing(c.Workspace, w)
			if err != nil {
				return Reply{}, err
			}
			if *asJSON {
				data, err := json.Marshal(b)
				return Reply{Text: string(data)}, err
			}
			return Reply{Text: briefingText(b)}, nil
		},
	})
}

// parseSince reads --since: an RFC 3339 time, a date, or an age back from now.
func parseSince(s string, now time.Time) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t, nil
	}
	if t, err := time.Parse(time.DateOnly, s); err == nil {
		return t, nil
	}
	if days, ok := strings.CutSuffix(s, "d"); ok {
		if n, err := strconv.Atoi(days); err == nil && n > 0 {
			return now.Add(-time.Duration(n) * 24 * time.Hour), nil
		}
	}
	if d, err := time.ParseDuration(s); err == nil && d > 0 {
		return now.Add(-d), nil
	}
	return time.Time{}, fmt.Errorf("--since takes an RFC 3339 time, a date (2006-01-02) or an age (36h, 3d), not %q", s)
}

// briefingText is the briefing for a person: pending first, then in flight,
// what happened, the last retro, next, and what SE is.
func briefingText(b issues.Briefing) string {
	var t strings.Builder
	fmt.Fprintf(&t, "SE briefing for %s, %s\n", b.Repo, b.At.Format(time.RFC3339))

	t.WriteString("\n## Waits on you\n")
	if len(b.Pending) == 0 {
		t.WriteString("Nothing waits on you.\n")
	}
	for _, p := range b.Pending {
		fmt.Fprintf(&t, "- #%d %s (%s, holds up %d)\n  %s\n  %s\n", p.Number, p.Title, p.Source, p.Holds, p.Reason, p.URL)
	}

	t.WriteString("\n## In flight\n")
	if len(b.InFlight) == 0 {
		t.WriteString("Nothing is claimed.\n")
	}
	for _, f := range b.InFlight {
		pr := ""
		if f.PR > 0 {
			pr = fmt.Sprintf("PR #%d %s; ", f.PR, f.PRURL)
		}
		fmt.Fprintf(&t, "- #%d %s: %s%s\n", f.Number, f.Title, pr, f.State)
	}
	if len(b.Findings) == 0 {
		t.WriteString("fleet check: healthy\n")
	} else {
		t.WriteString("fleet check:\n")
		for _, f := range b.Findings {
			t.WriteString(indent(findingText(f)) + "\n")
		}
	}

	fmt.Fprintf(&t, "\n## What happened (%s)\n", b.Window)
	if len(b.Happened) == 0 {
		t.WriteString("Nothing closed.\n")
	}
	for _, c := range b.Happened {
		var tags []string
		if c.Run != "" {
			tags = append(tags, c.Run)
		}
		if c.NotPlanned {
			tags = append(tags, "not planned")
		}
		if c.Person {
			tags = append(tags, "went to a person")
		}
		if c.PR > 0 {
			tags = append(tags, fmt.Sprintf("PR #%d", c.PR))
		}
		tag := ""
		if len(tags) > 0 {
			tag = " [" + strings.Join(tags, ", ") + "]"
		}
		fmt.Fprintf(&t, "- #%d %s%s, closed %s\n", c.Number, c.Title, tag, c.At.Format(time.RFC3339))
		if c.Done != "" {
			fmt.Fprintf(&t, "  %s\n", c.Done)
		}
	}

	t.WriteString("\n## Last retro\n")
	if b.Retro == nil {
		t.WriteString("No retro has run.\n")
	} else {
		fmt.Fprintf(&t, "#%d %s, closed %s\n%s\n", b.Retro.Number, b.Retro.Title, b.Retro.At.Format(time.RFC3339), b.Retro.URL)
		for _, h := range b.Retro.Headlines {
			fmt.Fprintf(&t, "- %s\n", h)
		}
	}

	t.WriteString("\n## Next\n")
	if b.Next == nil {
		t.WriteString("No se issue is ready.\n")
	} else {
		fmt.Fprintf(&t, "se issue pull would take #%d %s\n%s\n", b.Next.Number, b.Next.Title, b.Next.URL)
	}
	fmt.Fprintf(&t, "%d ready, %d claimed, %d blocked, %d in trees\n", b.Counts.Ready, b.Counts.Claimed, b.Counts.Blocked, b.Counts.InTrees)
	fmt.Fprintf(&t, "Queue: %s se issue tree tells the detail.\n", b.Queue.Line())

	t.WriteString("\n## What SE is\n")
	for _, l := range b.About.Lines {
		t.WriteString(l + "\n")
	}
	for _, l := range b.About.Links {
		fmt.Fprintf(&t, "- %s: %s\n", l.Path, l.URL)
	}
	return strings.TrimRight(t.String(), "\n")
}

func indent(s string) string { return "  " + strings.ReplaceAll(s, "\n", "\n  ") }
