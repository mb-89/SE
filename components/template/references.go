package template

import (
	"fmt"
	"regexp"
	"strings"
)

// A template names code as "<module>:<NAME>", a script beside scripts/templates.py (its docstring,
// "Fields" and "Adapters"). The Go engine holds the Go port of each name SE's templates use here;
// the shared cases hold each to the Python one it ports. A name it does not hold does not load.

// ShapeFunc is a title's shape that is a function: its answer, where not empty, is the warning.
type ShapeFunc func(title string) string

// References are the names SE's templates give, each as Go holds it: a list of choices, a pattern or
// a shape function.
var References = map[string]any{
	"work_tickets:RELEASE_KINDS":         []string{"feature", "feat", "fix", "perf", "chore", "docs", "test"},
	"work_tickets:RELEASE_ORDER":         []string{"patch", "minor", "major"},
	"review:VERDICTS":                    []string{"pass", "pass with open points", "decline"},
	"work_tickets:name_refusal":          ShapeFunc(nameRefusal),
	"work_tickets:MERGE_SUBJECT_PATTERN": regexp.MustCompile(`Integrate [^\s:()]+|Release v\d+\.\d+\.\d+`),
}

// The name rule (work_tickets.py `NAME_PATTERN`, the work model's Issues).
const (
	nameWords   = 5
	nameExample = "branch-cleanup-on-pr-close"
)

var (
	namePattern    = regexp.MustCompile(fmt.Sprintf(`^(?:[a-z0-9]+(?:-[a-z0-9]+){0,%d})$`, nameWords-1))
	oldNamePattern = regexp.MustCompile(`^(?:[a-z]+/[a-z0-9]+(?:-[a-z0-9]+)*-\d{8})$`)
	dateSuffix     = regexp.MustCompile(`-\d{8}$`)
	leadingLabel   = regexp.MustCompile(`^\s*\w+:\s*`)
	nameWord       = regexp.MustCompile(`[a-z0-9]+`)
	otherChar      = regexp.MustCompile(`[^A-Za-z0-9-]`)
	badDashes      = regexp.MustCompile(`--|^-|-$`)
	capital        = regexp.MustCompile(`[A-Z]`)
)

// shortName is work_tickets.py `short_name`: the name derived from a text.
func shortName(text string) string {
	topic := strip(text)
	if loc := leadingLabel.FindStringIndex(topic); loc != nil && loc[1] < len(topic) && !isSpace(rune(topic[loc[1]])) {
		topic = topic[loc[1]:]
	}
	if oldNamePattern.MatchString(topic) {
		_, after, _ := strings.Cut(topic, "/")
		topic = dateSuffix.ReplaceAllString(after, "")
	}
	found := nameWord.FindAllString(casefold(topic), -1)
	if len(found) > nameWords {
		found = found[:nameWords]
	}
	if len(found) == 0 {
		return "item"
	}
	return strings.Join(found, "-")
}

// nameRefusal is work_tickets.py `name_refusal`: why a name breaks the name rule, with a shorter
// name to use; "" where it follows it.
func nameRefusal(name string) string {
	name = strip(name)
	if namePattern.MatchString(name) || oldNamePattern.MatchString(name) {
		return ""
	}
	count := 0
	for _, word := range strings.Split(name, "-") {
		if word != "" {
			count++
		}
	}
	var wrong []string
	if count > nameWords {
		wrong = append(wrong, fmt.Sprintf("it has %d words", count))
	}
	if capital.MatchString(name) {
		wrong = append(wrong, "it has a capital")
	}
	if other := otherChar.FindString(name); other != "" {
		wrong = append(wrong, "it has a character other than a letter, a digit or a dash, such as "+repr(other))
	}
	if badDashes.MatchString(name) {
		wrong = append(wrong, "its dashes are not single dashes between words")
	}
	why := ""
	if len(wrong) > 0 {
		why = " (" + strings.Join(wrong, "; ") + ")"
	}
	return fmt.Sprintf("the name %s breaks the name rule%s: a name is 1 to %d words of lowercase letters and digits joined by single dashes, such as `%s`; keep the words that matter, for example `%s` (work model, Issues)",
		repr(name), why, nameWords, nameExample, shortName(name))
}

var fenceItem = regexp.MustCompile(`^([ \t]*)- `)

// pughProblems is deck.py `pugh_problems`: what SE asks of a pugh fence.
func pughProblems(text string) []string {
	start, end, ok := fenceSpan(text, "pugh")
	if !ok {
		return []string{"no `pugh` fence: write the options as obs's ```pugh fence"}
	}
	lines := splitLines(text[start:end], false)
	if len(lines) > 0 {
		lines = lines[1:]
	}
	if len(lines) > 0 && fence.MatchString(lines[len(lines)-1]) {
		lines = lines[:len(lines)-1]
	}
	var problems []string
	for _, want := range []struct {
		key   string
		least int
	}{{"criteria", 1}, {"candidates", 2}} {
		count, found := fenceItems(lines, want.key)
		switch {
		case !found:
			problems = append(problems, fmt.Sprintf("the `pugh` fence has no `%s:`; write its %s, as the decision skill's fence says", want.key, want.key))
		case count < want.least:
			problems = append(problems, fmt.Sprintf("the `pugh` fence's `%s` lists %d; write at least %d", want.key, count, want.least))
		}
	}
	return problems
}

// fenceItems is deck.py `_items`: how many items the top-level key of a fence's YAML lists.
func fenceItems(lines []string, key string) (int, bool) {
	keyLine := regexp.MustCompile(`^` + regexp.QuoteMeta(key) + `[ \t]*:`)
	start := -1
	for i, line := range lines {
		if keyLine.MatchString(line) {
			start = i
			break
		}
	}
	if start < 0 {
		return 0, false
	}
	_, after, _ := strings.Cut(lines[start], ":")
	if flow := strip(after); flow != "" {
		inner := flow
		if strings.HasPrefix(flow, "[") && strings.HasSuffix(flow, "]") {
			inner = flow[1 : len(flow)-1]
		}
		depth, count, seen := 0, 0, false
		for _, c := range inner {
			if c == '[' || c == '{' {
				depth++
			}
			if c == ']' || c == '}' {
				depth--
			}
			if c == ',' && depth == 0 {
				if seen {
					count++
				}
				seen = false
			} else if !isSpace(c) {
				seen = true
			}
		}
		if seen {
			count++
		}
		return count, true
	}
	count, indent := 0, -1
	for _, line := range lines[start+1:] {
		if strip(line) != "" && !(line != "" && isSpace(rune(line[0]))) && !strings.HasPrefix(line, "- ") {
			break
		}
		if m := fenceItem.FindStringSubmatch(line); m != nil && (indent < 0 || indent == len(m[1])) {
			indent, count = len(m[1]), count+1
		}
	}
	return count, true
}
