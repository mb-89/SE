package rules

import (
	"path"
	"regexp"
	"strings"
)

// isProse says whether a path is prose the consistency rules read: every
// Markdown file, and the YAML in spec/.
func isProse(p string) bool {
	return path.Ext(p) == ".md" || (strings.HasPrefix(p, "spec/") && path.Ext(p) == ".yaml")
}

// snippet is one piece of code a prose file holds, with its line.
type snippet struct {
	line   int
	text   string
	fenced bool
}

// codeOf answers the code a prose file holds: each inline code span, and each
// line of a fenced block. A span stays on its line. A manifest section is
// left out: se made it from its owners, and the manifest rule checks it.
func codeOf(text []byte) []snippet {
	var out []snippet
	fence, made := "", false
	for i, line := range strings.Split(string(text), "\n") {
		trimmed := strings.TrimSpace(line)
		switch {
		case made:
			made = line != manifestClose
			continue
		case manifestOpen.MatchString(line):
			made = true
			continue
		}
		if fence != "" {
			if strings.HasPrefix(trimmed, fence) {
				fence = ""
				continue
			}
			out = append(out, snippet{line: i + 1, text: line, fenced: true})
			continue
		}
		if f := fenceOf(trimmed); f != "" {
			fence = f
			continue
		}
		for _, s := range spansOf(line) {
			out = append(out, snippet{line: i + 1, text: s})
		}
	}
	return out
}

// fenceOf answers the fence a line opens, or "".
func fenceOf(trimmed string) string {
	for _, f := range []string{"```", "~~~"} {
		if strings.HasPrefix(trimmed, f) {
			return f
		}
	}
	return ""
}

// spansOf answers a line's inline code spans: a run of backticks to the next
// run of the same length.
func spansOf(line string) []string {
	var out []string
	for i := 0; i < len(line); {
		if line[i] != '`' {
			i++
			continue
		}
		n := 0
		for i+n < len(line) && line[i+n] == '`' {
			n++
		}
		tick := strings.Repeat("`", n)
		rest := line[i+n:]
		end := -1
		for j := 0; j < len(rest); {
			k := strings.Index(rest[j:], tick)
			if k < 0 {
				break
			}
			k += j
			m := k
			for m < len(rest) && rest[m] == '`' {
				m++
			}
			if m-k == n {
				end = k
				break
			}
			j = m
		}
		if end < 0 {
			i += n
			continue
		}
		out = append(out, strings.TrimSpace(rest[:end]))
		i += n + end + n
	}
	return out
}

// link is a Markdown link's target, with its line.
type link struct {
	line   int
	target string
}

var linkPattern = regexp.MustCompile(`\]\(([^)\s]+)(?:\s+"[^"]*")?\)`)

// linksOf answers the link targets of a prose file outside its code.
func linksOf(text []byte) []link {
	var out []link
	fence := ""
	for i, line := range strings.Split(string(text), "\n") {
		trimmed := strings.TrimSpace(line)
		if fence != "" {
			if strings.HasPrefix(trimmed, fence) {
				fence = ""
			}
			continue
		}
		if fence = fenceOf(trimmed); fence != "" {
			continue
		}
		for _, s := range spansOf(line) {
			line = strings.Replace(line, s, "", 1)
		}
		for _, m := range linkPattern.FindAllStringSubmatch(line, -1) {
			out = append(out, link{line: i + 1, target: m[1]})
		}
	}
	return out
}
