// Measures a cold se issue pull's GitHub reads against a repository (#375, #419): its time and its requests by kind; run from src/ as go run ./scripts/cold-pull.go OWNER/NAME [runs].
//go:build ignore

package main

import (
	"errors"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strconv"
	"sync"

	"github.com/mb-89/SE/src/internal/io/clock"
	"github.com/mb-89/SE/src/internal/io/github"
	"github.com/mb-89/SE/src/internal/issues"
)

// counting counts the reads by kind: the path with its numbers and query left out.
type counting struct {
	github.GitHub
	mu    sync.Mutex
	kinds map[string]int
}

var digits = regexp.MustCompile(`[0-9]+`)

func (c *counting) note(path string) {
	kind := digits.ReplaceAllString(path, "N")
	if k := regexp.MustCompile(`\?.*`).FindStringIndex(kind); k != nil && !regexp.MustCompile(`activity|issues\?`).MatchString(kind) {
		kind = kind[:k[0]]
	}
	c.mu.Lock()
	c.kinds[kind]++
	c.mu.Unlock()
}

func (c *counting) Get(path string) ([]byte, error)  { c.note(path); return c.GitHub.Get(path) }
func (c *counting) List(path string) ([]byte, error) { c.note(path); return c.GitHub.List(path) }

func main() {
	runs := 1
	if len(os.Args) > 2 {
		runs, _ = strconv.Atoi(os.Args[2])
	}
	for range runs {
		c := &counting{GitHub: github.Real(), kinds: map[string]int{}}
		s := issues.Source{Repo: os.Args[1], GitHub: github.Record(c), Clock: clock.Real()}
		wall := clock.Real()
		began := wall.Now()
		next, ok, _, err := s.Pull()
		took := wall.Now().Sub(began)
		if err != nil && !errors.Is(err, github.ErrReadOnly) {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		total := 0
		var kinds []string
		for k, n := range c.kinds {
			total += n
			kinds = append(kinds, fmt.Sprintf("%4d %s", n, k))
		}
		sort.Sort(sort.Reverse(sort.StringSlice(kinds)))
		fmt.Printf("%.2fs, %d requests, next #%d (%v)\n", took.Seconds(), total, next.Number, ok)
		for _, k := range kinds {
			fmt.Println("  " + k)
		}
	}
}
