// Package main is the fixture's one program: what it reaches is production.
package main

import (
	"fmt"

	"example.com/fix/internal/lib"
)

func main() {
	lib.Register("only")
	fmt.Println(lib.Used(), lib.Copy("a"), lib.Again("b"), lib.Near(1), lib.Far(2), kind("x"), wide(1, 2, 3, 4, 5, 6))
	var s lib.Store = lib.Disk{}
	fmt.Println(s.Get("k"))
}

// kind switches on a kind with three arms.
func kind(k string) int {
	switch k {
	case "a":
		return 1
	case "b":
		return 2
	case "c":
		return 3
	}
	return 0
}

// wide takes six parameters.
func wide(a, b, c, d, e, f int) int { return a + b + c + d + e + f }
