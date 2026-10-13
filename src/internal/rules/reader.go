package rules

import (
	"path"
	"strings"
)

func init() {
	register(Rule{
		Name:    "reader",
		Doc:     "every Markdown file names its readers in one line at the top: Reader: …, under its title",
		Applies: func(p string) bool { return path.Ext(p) == ".md" },
		Check:   reader,
	})
}

func reader(_ *Repo, p string, text []byte) []Finding {
	lines := strings.Split(string(text), "\n")
	i := 0
	if len(lines) > 0 && strings.TrimSpace(lines[0]) == "---" {
		for i = 1; i < len(lines) && strings.TrimSpace(lines[i]) != "---"; i++ {
		}
		i++
	}
	skipBlank := func() {
		for i < len(lines) && strings.TrimSpace(lines[i]) == "" {
			i++
		}
	}
	skipBlank()
	if i < len(lines) && strings.HasPrefix(lines[i], "# ") {
		i++
		skipBlank()
	}
	if i < len(lines) && (strings.HasPrefix(lines[i], "Reader: ") || strings.HasPrefix(lines[i], "Readers: ")) {
		return nil
	}
	line := i + 1
	if i >= len(lines) {
		line = len(lines)
	}
	return []Finding{{Path: p, Line: line, Rule: "reader", Message: "the file names no reader; under its title, write one line: Reader: <who reads it, and what for>"}}
}
