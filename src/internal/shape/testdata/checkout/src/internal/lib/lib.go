// Package lib is the fixture's library: one program imports it.
package lib

import "strings"

// Store is an interface with one implementation and no fake.
type Store interface {
	Get(key string) string
}

// Disk is Store's one implementation.
type Disk struct{}

// Get answers the key.
func (Disk) Get(key string) string { return key }

// Clock has a fake, in fake.go.
type Clock interface {
	Now() int
}

// Wall is Clock's real implementation.
type Wall struct{}

// Now answers the time.
func (Wall) Now() int { return 1 }

var registry []string

// Register is a registry with one entry.
func Register(name string) { registry = append(registry, name) }

// Used is what the program uses.
func Used() int { return len(registry) }

// OnlyTests is reached from the tests alone.
func OnlyTests() int { return 7 }

// Old is kept for issues from before the move, whose last one has closed.
func Old() int { return 0 }

// Copy and Again are the same function twice.
func Copy(s string) string {
	parts := strings.Split(s, ",")
	out := []string{}
	for _, p := range parts {
		if strings.TrimSpace(p) != "" {
			out = append(out, strings.ToUpper(p))
		}
	}
	return strings.Join(out, ";")
}

// Again is Copy again.
func Again(s string) string {
	parts := strings.Split(s, ",")
	out := []string{}
	for _, p := range parts {
		if strings.TrimSpace(p) != "" {
			out = append(out, strings.ToUpper(p))
		}
	}
	return strings.Join(out, ";")
}

// Near and Far differ in their names and literals alone.
func Near(n int) int {
	total := 0
	for k := 0; k < n; k++ {
		if k%2 == 0 {
			total += k * 3
		} else {
			total -= k
		}
	}
	return total + n
}

// Far is Near with other names.
func Far(m int) int {
	sum := 0
	for j := 0; j < m; j++ {
		if j%5 == 0 {
			sum += j * 7
		} else {
			sum -= j
		}
	}
	return sum + m
}
