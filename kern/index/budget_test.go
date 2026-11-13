package index_test

import (
	"fmt"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/index"
	"github.com/mb-89/kern/index/fixture"
)

// CheckBudget is the catalog check's budget at start, for bigCatalog's 200
// instances: about ten times its slowest measured run, 1.74 ms (kern's README,
// "The catalog check's budget").
const CheckBudget = 20 * time.Millisecond

// bigCatalog is a wiring of n instances: a source and a chain of doublers,
// each reading the last, plus a tally reading the source's list, its command
// collected, so every check of the start runs on every instance.
func bigCatalog(n int) []byte {
	var b strings.Builder
	b.WriteString("[instances.src]\ncomponent = \"source\"\n\n[instances.t]\ncomponent = \"tally\"\nconfig = { scale = 2 }\n\n")
	for i := range n - 2 {
		fmt.Fprintf(&b, "[instances.\"chain/d%d\"]\ncomponent = \"doubler\"\n\n", i)
	}
	b.WriteString("[wires]\n\"t.numbers\" = \"src.list\"\n\"chain/d0.x\" = \"src.n\"\n")
	for i := 1; i < n-2; i++ {
		fmt.Fprintf(&b, "\"chain/d%d.x\" = \"chain/d%d.twice\"\n", i, i-1)
	}
	return []byte(b.String())
}

// check reads the wiring and checks the catalog it makes, as the start does
// before any derivation runs.
func check(data []byte) error {
	w, err := index.ParseWiring(data)
	if err != nil {
		return err
	}
	_, err = index.Collect(w, source, doubler, fixture.Tally)
	return err
}

// The catalog check at start keeps its budget: the median of nine runs.
func TestTheCatalogCheckKeepsItsBudget(t *testing.T) {
	t.Parallel()
	data := bigCatalog(200)
	runs := make([]time.Duration, 9)
	for i := range runs {
		began := time.Now()
		must(t, check(data))
		runs[i] = time.Since(began)
	}
	slices.Sort(runs)
	if median := runs[len(runs)/2]; median > CheckBudget {
		t.Fatalf("the catalog check of 200 instances took %v (median of %v), over its budget of %v", median, runs, CheckBudget)
	}
}

func BenchmarkTheCatalogCheck(b *testing.B) {
	for _, n := range []int{20, 200} {
		data := bigCatalog(n)
		b.Run(fmt.Sprintf("%d instances", n), func(b *testing.B) {
			for b.Loop() {
				if err := check(data); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
