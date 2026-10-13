package rules

import (
	"bytes"
	"path"
	"regexp"
)

// The marker is spelled in two halves, so this file does not break its own rule.
var (
	marker   = regexp.MustCompile(`\b` + "TO" + "DO" + `\b`)
	numbered = regexp.MustCompile(`\b` + "TO" + "DO" + `\b.*#[0-9]+`)
)

// code is the files the marker rule reads: the ones a program or a person runs.
var code = map[string]bool{".go": true, ".ts": true, ".tsx": true, ".js": true, ".sh": true, ".yml": true, ".yaml": true}

func init() {
	register(Rule{
		Name:    "todo-issue",
		Doc:     "a " + "TO" + "DO in code names its issue, like " + "TO" + "DO(#12)",
		Applies: func(p string) bool { return code[path.Ext(p)] },
		Check:   todoIssue,
	})
}

func todoIssue(_ *Repo, p string, text []byte) []Finding {
	var found []Finding
	for i, line := range bytes.Split(text, []byte("\n")) {
		if marker.Match(line) && !numbered.Match(line) {
			found = append(found, Finding{Path: p, Line: i + 1, Rule: "todo-issue", Message: "it names no issue; write " + "TO" + "DO(#<n>)"})
		}
	}
	return found
}
