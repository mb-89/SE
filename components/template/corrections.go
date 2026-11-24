package template

import (
	"fmt"
	"regexp"
	"strings"
)

// The correction pass, as scripts/templates.py's docstring (Corrections) owns it: before it checks,
// a fill corrects what cannot change the document's meaning, and nothing else, reports each change
// and records the kinds made in the document. The shared cases hold it to the Python engine's
// (testdata/cases/corrections.json).

// Corrections are the kinds of correction, in the order the pass applies them.
var Corrections = []string{"line-ending", "whitespace", "heading", "list-marker", "quote-marker", "none", "not-in-input"}

var (
	listMarker     = regexp.MustCompile(`^([ \t]*)[*+]([ \t]+)`)
	numberMarker   = regexp.MustCompile(`^([ \t]*)([0-9]+)\)([ \t]+)`)
	quoteMarker    = regexp.MustCompile(`^([ \t]*)>([^ \t>])`)
	thematicBreak  = regexp.MustCompile(`^[ \t]*\*(?:[ \t]*\*){2,}[ \t]*$`)
	noneSpelling   = regexp.MustCompile(`(?i)^none\.?$`)
	correctedLine  = regexp.MustCompile(`^[ \t]*<!-- se:corrected [a-z -]+ -->[ \t]*$`)
	correctedKey   = regexp.MustCompile(`^corrected[ \t]*:`)
	correctedMark  = "<!-- se:corrected %s -->"
	snippetKinds   = []string{"rows", "case"}
	uncorrectedSet = append([]string{"code", "node", "register"}, snippetKinds...)
)

// Correction is one text the pass changed: its field (`body` for the document's line endings), the
// kinds it made, and the text before and after.
type Correction struct {
	Field  string   `json:"field"`
	Kinds  []string `json:"kinds"`
	Before string   `json:"before"`
	After  string   `json:"after"`
}

func (c Correction) String() string {
	return fmt.Sprintf("corrected: %s [%s]: %s -> %s", c.Field, joinStrings(c.Kinds), repr(c.Before), repr(c.After))
}

func orderedKinds(kinds map[string]bool) []string {
	var out []string
	for _, kind := range Corrections {
		if kinds[kind] {
			out = append(out, kind)
		}
	}
	return out
}

// correctedLine is one line outside a fence with its trailing whitespace, list marker and quote
// marker corrected, each kind made added to kinds.
func correctLine(line string, kinds map[string]bool) string {
	text := strings.TrimRight(line, " \t")
	if text != line {
		kinds["whitespace"] = true
	}
	if m := listMarker.FindStringSubmatchIndex(text); m != nil && !thematicBreak.MatchString(text) {
		text = text[m[2]:m[3]] + "-" + text[m[4]:m[5]] + text[m[1]:]
		kinds["list-marker"] = true
	} else if m := numberMarker.FindStringSubmatchIndex(text); m != nil {
		text = text[m[2]:m[3]] + text[m[4]:m[5]] + "." + text[m[6]:m[7]] + text[m[1]:]
		kinds["list-marker"] = true
	}
	if m := quoteMarker.FindStringSubmatchIndex(text); m != nil {
		text = text[m[2]:m[3]] + "> " + text[m[4]:]
		kinds["quote-marker"] = true
	}
	return text
}

// proseStep is templates.py `_fence_state`: the fence state after line, and whether line is text
// outside a fence (not code, no fence line).
func proseStep(state, line string) (string, bool) {
	m := fence.FindStringSubmatch(line)
	switch {
	case state == "" && m != nil:
		return m[1], false
	case state != "":
		if m != nil && strings.HasPrefix(m[1], state) {
			return "", false
		}
		return state, false
	}
	return "", true
}

// CorrectedText is templates.py `corrected_text`: text with the corrections that cannot change its
// meaning, and the kinds made. With whole (a line, a choice, an entry of a list or an object's
// value) the spaces and tabs before the text go too.
func CorrectedText(text string, whole bool) (string, []string) {
	kinds := map[string]bool{}
	if strings.Contains(text, "\r") {
		text = strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n")
		kinds["line-ending"] = true
	}
	lines := strings.Split(text, "\n")
	state := ""
	for i, line := range lines {
		var prose bool
		state, prose = proseStep(state, line)
		if prose {
			lines[i] = correctLine(line, kinds)
		}
	}
	joined := strings.Join(lines, "\n")
	if whole {
		text = strings.Trim(joined, " \t\n")
	} else {
		text = strings.Trim(joined, "\n")
	}
	if text != joined {
		kinds["whitespace"] = true
	}
	bare := strip(text)
	closing := bare[len(strings.TrimRight(bare, ".:")):]
	spelled, kind := "", ""
	if !comment.MatchString(text) && noneSpelling.MatchString(bare) {
		spelled, kind = "None"+closing, "none"
	} else if !comment.MatchString(text) && notInInput(bare) {
		spelled, kind = NotInInput+closing, "not-in-input"
	}
	if kind != "" && spelled != text {
		if spelled == bare {
			kind = "whitespace"
		}
		kinds[kind] = true
		text = spelled
	}
	return text, orderedKinds(kinds)
}

// correctable is templates.py `_correctable`: whether the pass touches the field's value.
func correctable(item *Field) bool {
	return !(item.Source == "title" || item.Verbatim || item.Node != "" || item.Fence != "" || in(item.Kind, uncorrectedSet))
}

// Correct is templates.py `correct`: the values with each correctable field's texts corrected, and
// one Correction for each text that changed.
func Correct(t *Template, values Object) (Object, []Correction) {
	given := values.Copy()
	var found []Correction
	for _, item := range t.Fields {
		value, ok := given.Get(item.Name)
		if !ok || !correctable(item) {
			continue
		}
		fixed := func(v any, whole bool) any {
			text, isText := v.(string)
			if !isText || wholeComment(text) {
				return v
			}
			after, kinds := CorrectedText(text, whole)
			if len(kinds) > 0 {
				found = append(found, Correction{item.Name, kinds, text, after})
			}
			return after
		}
		switch x := value.(type) {
		case string:
			given.Set(item.Name, fixed(x, item.Kind != "text"))
		case []any:
			list := make([]any, len(x))
			for i, entry := range x {
				if o, isObject := entry.(Object); isObject && o.Has("text") {
					entryCopy := o.Copy()
					entryCopy.Set("text", fixed(o.Value("text"), true))
					list[i] = entryCopy
				} else {
					list[i] = fixed(entry, true)
				}
			}
			given.Set(item.Name, list)
		case Object:
			o := make(Object, len(x))
			for i, pair := range x {
				o[i] = Pair{pair.Key, fixed(pair.Value, true)}
			}
			given.Set(item.Name, o)
		}
	}
	return given, found
}

// proseLine is the index of the first line from start that is wanted and outside a fence, else -1.
func proseLine(lines []string, start int, wanted string) int {
	state := ""
	for i := start; i < len(lines); i++ {
		var prose bool
		state, prose = proseStep(state, lines[i])
		if prose && lines[i] == wanted {
			return i
		}
	}
	return -1
}

// CorrectBody is templates.py `correct_body`: a whole document corrected, and a Correction for each
// change: its line endings, each section heading that names a field but for its case or level, and
// each line of a correctable field's section outside a fence.
func CorrectBody(t *Template, body string) (string, []Correction) {
	if t.IsAdapter() || t.Message != "" {
		return body, nil
	}
	var found []Correction
	if strings.Contains(body, "\r") {
		body = strings.ReplaceAll(strings.ReplaceAll(body, "\r\n", "\n"), "\r", "\n")
		found = append(found, Correction{"body", []string{"line-ending"}, "\r\n", "\n"})
	}
	hashes := strings.Repeat("#", t.Level())
	doc := Parse(t, body, nil)
	lines := strings.Split(body, "\n")
	start := 0
	if loc := frontMatter.FindStringIndex(body); loc != nil {
		start = strings.Count(body[:loc[1]], "\n")
	}
	for _, item := range t.Fields {
		near, missed := doc.Misses[item.Name]
		if !item.ExactHeading || !missed {
			continue
		}
		if at := proseLine(lines, start, near); at >= 0 {
			want := hashes + " " + item.Heading
			lines[at] = want
			found = append(found, Correction{item.Name, []string{"heading"}, near, want})
		}
	}
	doc = Parse(t, strings.Join(lines, "\n"), nil)
	corrected := func(name string) bool {
		for _, c := range found {
			if c.Field == name {
				return true
			}
		}
		return false
	}
	type head struct{ line, field string }
	var heads []head
	for _, part := range doc.Parts {
		if part.Kind == "field" {
			want := hashes + " " + t.Field(part.Name).Heading
			if part.Heading != want && !corrected(part.Name) {
				found = append(found, Correction{part.Name, []string{"heading"}, part.Heading, want})
			}
		}
		if (part.Kind == "field" || part.Kind == "unknown" || part.Kind == "scope") && part.Heading != "" {
			field := ""
			if part.Kind == "field" {
				field = part.Name
			}
			heads = append(heads, head{part.Heading, field})
		}
	}
	state, current, at := "", "", 0
	for i := start; i < len(lines); i++ {
		line := lines[i]
		var prose bool
		state, prose = proseStep(state, line)
		if !prose {
			continue
		}
		if at < len(heads) && line == heads[at].line {
			current, at = heads[at].field, at+1
			continue
		}
		if current == "" {
			continue
		}
		item := t.Field(current)
		if item == nil || !correctable(item) {
			continue
		}
		kinds := map[string]bool{}
		fixed := correctLine(line, kinds)
		if len(kinds) > 0 {
			found = append(found, Correction{item.Name, orderedKinds(kinds), line, fixed})
			lines[i] = fixed
		}
	}
	return strings.Join(lines, "\n"), found
}

// RecordCorrections is templates.py `record_corrections`: the document recording the kinds of the
// corrections made, and no earlier record: a file in its front matter, any other document in a
// marker line after its template marker; a message and an adapter record none.
func RecordCorrections(t *Template, text string, corrections []Correction) string {
	made := map[string]bool{}
	for _, c := range corrections {
		for _, kind := range c.Kinds {
			made[kind] = true
		}
	}
	kinds := orderedKinds(made)
	if t.IsAdapter() || t.Message != "" {
		return text
	}
	if t.writesFile() {
		loc := frontMatter.FindStringIndex(text)
		if loc == nil {
			return text
		}
		head := text[:loc[1]]
		newline := "\n"
		if strings.Contains(head, "\r\n") {
			newline = "\r\n"
		}
		var lines []string
		for _, line := range strings.Split(head, newline) {
			if !correctedKey.MatchString(line) {
				lines = append(lines, line)
			}
		}
		if len(kinds) > 0 {
			at := len(lines) - 2
			for i, line := range lines {
				if strings.HasPrefix(line, "overlay:") {
					at = i + 1
					break
				}
			}
			quoted := make([]string, len(kinds))
			for i, kind := range kinds {
				quoted[i] = `"` + kind + `"`
			}
			lines = insertAt(lines, at, "corrected: ["+strings.Join(quoted, ", ")+"]")
		}
		return strings.Join(lines, newline) + text[loc[1]:]
	}
	var lines []string
	for _, line := range strings.Split(text, "\n") {
		if !correctedLine.MatchString(line) {
			lines = append(lines, line)
		}
	}
	if len(kinds) > 0 {
		for i, line := range lines {
			if strip(line) == t.MarkerLine() {
				lines = insertAt(lines, i+1, fmt.Sprintf(correctedMark, strings.Join(kinds, " ")))
				break
			}
		}
	}
	return strings.Join(lines, "\n")
}

func insertAt(lines []string, at int, line string) []string {
	out := append([]string{}, lines[:at]...)
	out = append(out, line)
	return append(out, lines[at:]...)
}
