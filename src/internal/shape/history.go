package shape

import (
	"maps"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
)

// commit is one change on main, as git log tells it.
type commit struct {
	Change
	at    time.Time
	files []string
}

// commits reads git log in Read's format, newest first.
func commits(log string) []commit {
	var out []commit
	for _, rec := range strings.Split(log, "\x1e") {
		lines := strings.Split(strings.TrimSpace(rec), "\n")
		head := strings.SplitN(lines[0], "\x1f", 3)
		if len(head) < 3 {
			continue
		}
		secs, err := strconv.ParseInt(head[1], 10, 64)
		if err != nil {
			continue
		}
		c := commit{Change: Change{SHA: head[0], Subject: head[2]}, at: time.Unix(secs, 0).UTC()}
		for _, f := range lines[1:] {
			if f = strings.TrimSpace(f); f != "" {
				c.files = append(c.files, f)
			}
		}
		c.Files = len(c.files)
		out = append(out, c)
	}
	return out
}

// history finds what the log tells: the files untouched longest, when each
// script came and whether the last retro has read it, and how many files a
// change touches.
func (s *scan) history() {
	log := commits(s.in.Log)
	last, added := map[string]time.Time{}, map[string]time.Time{}
	for _, c := range log {
		for _, f := range c.files {
			if _, ok := last[f]; !ok {
				last[f] = c.at
			}
			added[f] = c.at
		}
	}
	for _, f := range s.in.Tracked {
		if at, ok := last[f]; ok {
			s.f.Untouched = append(s.f.Untouched, Touched{f, at})
		}
	}
	sort.SliceStable(s.f.Untouched, func(a, b int) bool { return s.f.Untouched[a].Last.Before(s.f.Untouched[b].Last) })

	for _, p := range slices.Sorted(maps.Keys(s.in.Scripts)) {
		text := string(s.in.Scripts[p])
		sc := Script{Path: p, Added: added[p]}
		for _, line := range strings.Split(text, "\n") {
			l := strings.TrimSpace(line)
			if strings.HasPrefix(l, "#!") || (!strings.HasPrefix(l, "#") && !strings.HasPrefix(l, "//")) {
				continue
			}
			sc.Why = strings.TrimSuffix(strings.TrimSpace(strings.TrimPrefix(strings.TrimLeft(l, "#/ "), "Why:")), ".")
			break
		}
		sc.Read = !sc.Added.IsZero() && !s.in.ReadBy.IsZero() && !sc.Added.After(s.in.ReadBy)
		for _, c := range s.in.Commands {
			if strings.Contains(text, "se "+c.Name) {
				sc.Names = append(sc.Names, "se "+c.Name)
			}
		}
		s.f.Scripts = append(s.f.Scripts, sc)
	}

	var counts []int
	for _, c := range log {
		if c.Files == 0 {
			continue
		}
		if s.in.Since.IsZero() && len(counts) == recent || !s.in.Since.IsZero() && c.at.Before(s.in.Since) {
			break
		}
		counts = append(counts, c.Files)
		s.f.Widest = append(s.f.Widest, c.Change)
	}
	sort.SliceStable(s.f.Widest, func(a, b int) bool { return s.f.Widest[a].Files > s.f.Widest[b].Files })
	if s.f.Changes = len(counts); s.f.Changes > 0 {
		sort.Ints(counts)
		s.f.MedianFiles, s.f.MaxFiles = counts[len(counts)/2], counts[len(counts)-1]
	}
}
