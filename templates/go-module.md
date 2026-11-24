---
# A Go module: its go.mod, one package with its entry and a test. `templates.py scaffold go-module
# --path <folder> --says <line>` writes one, and SE's hook refuses a go.mod written without its
# marker or its module and go lines. scripts/templates.py's docstring (Code templates) owns this
# note's format.
name: go-module
version: 1.0.0
kind: code
reader: fleet
says: "A Go module: its go.mod, its package with the entry Run, a test, and slots for its own content."
tags: ["code", "go"]
applies:
  actions: ["file.write"]
  paths: ["go.mod", "**/go.mod"]
  marker_pattern: "// se:template [\\w.-]+/go-module \\d+\\.\\d+\\.\\d+"
adapter:
  lines:
    - pattern: "// se:template [\\w.-]+/go-module 1\\.\\d+\\.\\d+"
      first: true
      says: "the template marker: go.mod's first line is `// se:template se/go-module <version>`, the template and version it derives from"
    - pattern: "module \\S+"
      says: "the module line: `module <path>`, a path that names no host"
    - pattern: "go \\d+\\.\\d+(\\.\\d+)?"
      says: "the go line: `go <version>`, the language version the module is written for"
---

## go.mod

````go
// se:template {{template}} {{version}}
// {{says}}
module {{package}}

go 1.24
````

## {{package}}.go

````go
// se:template {{template}} {{version}}

// Package {{package}}: {{says}}
//
// Slot: say here what the package offers and who calls it.
package {{package}}

// In is what Run reads. Slot: its fields.
type In struct {
	Words []string
}

// Out is what Run answers. Slot: its fields.
type Out struct {
	Count int
}

// Run is the module's entry: what it answers for in. Slot: its own logic.
func Run(in In) (Out, error) {
	return Out{Count: len(in.Words)}, nil
}
````

## {{package}}_test.go

````go
// se:template {{template}} {{version}}

package {{package}}_test

import (
	"testing"

	"{{package}}"
)

// Run answers for what it reads. Slot: the tests of its own logic.
func TestRunAnswersForWhatItReads(t *testing.T) {
	out, err := {{package}}.Run({{package}}.In{Words: []string{"a", "b"}})
	if err != nil {
		t.Fatal(err)
	}
	if out.Count != 2 {
		t.Fatalf("Run counted %d words, want 2", out.Count)
	}
}
````
