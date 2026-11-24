package template

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
)

var (
	notPicked   = regexp.MustCompile(`(?im)^[ \t>*_-]*not picked[*_]*:[*_]*[ \t]*\S`)
	board       = regexp.MustCompile(`(?im)^[ \t]*(?:[-*+][ \t]+)?\**(status|labels?|priority|assignee|milestone)\**[ \t]*:`)
	bareNumber  = regexp.MustCompile(`#\d+\b`)
	codeSpan    = regexp.MustCompile("`[^`\\n]*`")
	link        = regexp.MustCompile(`\[[^\]]*\]\([^)]*\)|https?://\S+`)
	pathLike    = regexp.MustCompile(`^(?:\S*[/\\]\S*|\S+\.(py|md|toml|go|json|yml|yaml|sh|ps1))$`)
	bareIssue   = regexp.MustCompile(`^(?:(?:[\w.-]+/[\w.-]+)?#\d+|<?https?://\S+>?)$`)
	sentenceEnd = regexp.MustCompile("[.!?][ \\t]+[A-Z(\"'`]")
	listStart   = regexp.MustCompile(`\n[ \t]*(?:[-*+]|\d+[.)])[ \t]`)
	numberTitle = regexp.MustCompile(`^#?\d+$`)
	choiceSplit = regexp.MustCompile(`[\s,.;:]+`)
	quoteSpans  = regexp.MustCompile(`"([^"\n]+)"|“([^”\n]+)”`)
	quoteLine   = regexp.MustCompile(`^[ \t]*>[ \t]?(.*?)[ \t]*$`)
	placeholder = set("", noResponse, "tbd", "tba", "...", "…", "-", "?", "n/a", ">", "1.")
)

const noneWord = "none"

// Finding is one problem a check found: the field, the rule, refuse or warn, and the fix.
type Finding struct {
	Field    string `json:"field"`
	Rule     string `json:"rule"`
	Severity string `json:"severity"`
	Fix      string `json:"fix"`
}

func (f Finding) String() string {
	return fmt.Sprintf("%s: %s [%s]: %s", f.Severity, f.Field, f.Rule, f.Fix)
}

// Refused reports whether a finding of found refuses.
func Refused(found []Finding) bool {
	for _, f := range found {
		if f.Severity == Refuse {
			return true
		}
	}
	return false
}

func plain(value any) string {
	switch x := value.(type) {
	case Object:
		lines := make([]string, len(x))
		for i, pair := range x {
			lines[i] = pair.Key + ": " + str(pair.Value)
		}
		return strings.Join(lines, "\n")
	case []any:
		var lines []string
		for _, entry := range x {
			if wholeComment(str(entry)) {
				continue
			}
			if o, ok := entry.(Object); ok {
				text := ""
				if v, has := o.Get("text"); has {
					text = str(v)
				} else if !o.Has("done") {
					values := make([]string, len(o))
					for i, pair := range o {
						values[i] = str(pair.Value)
					}
					text = strings.Join(values, " | ")
				}
				lines = append(lines, text)
			} else {
				lines = append(lines, str(entry))
			}
		}
		return strings.Join(lines, "\n")
	}
	if !truthy(value) {
		return ""
	}
	return str(value)
}

func squash(text string) string { return casefold(joinWords(comment.ReplaceAllString(text, ""))) }

func notInInput(value any) bool {
	switch x := value.(type) {
	case Object:
		return len(x) == 1 && notInInput(x[0].Key) && strip(plainText(x[0].Value)) == ""
	case []any:
		var entries []any
		for _, entry := range x {
			if !wholeComment(str(entry)) {
				entries = append(entries, entry)
			}
		}
		if len(entries) != 1 {
			return false
		}
		if o, ok := entries[0].(Object); ok {
			text := ""
			if v, has := o.Get("text"); has {
				text = str(v)
			}
			return notInInput(text)
		}
		return notInInput(entries[0])
	case string:
		return strip(strings.TrimRight(squash(x), ".:")) == casefold(NotInInput)
	}
	return false
}

// plainText is Python's str(value or "").
func plainText(value any) string {
	if !truthy(value) {
		return ""
	}
	return str(value)
}

func emptiness(item *Field, value any, present bool) string {
	if !present || value == nil {
		return "missing"
	}
	text := plain(value)
	var lines []string
	for _, line := range splitLines(comment.ReplaceAllString(text, ""), false) {
		lines = append(lines, rstrip(strings.TrimLeft(line, "> ")))
	}
	squashed := casefold(joinWords(strings.Join(lines, "\n")))
	if strings.TrimRight(squashed, ".") == noneWord {
		if item.NoneOK {
			return ""
		}
		return "placeholder"
	}
	if list, ok := value.([]any); item.Kind == "issue" && ok && len(list) > 0 {
		all := true
		for _, entry := range list {
			if strings.TrimRight(squash(str(entry)), ".") != noneWord {
				all = false
			}
		}
		if all {
			if item.NoneOK {
				return ""
			}
			return "placeholder"
		}
	}
	if placeholder[squashed] {
		if squashed == "" || squashed == noResponse || squashed == ">" || squashed == "1." {
			return "empty"
		}
		return "placeholder"
	}
	says := squash(item.Says)
	if says != "" && (squashed == says || (chars(says) >= 30 && strings.Contains(squashed, says))) {
		return "says"
	}
	return ""
}

func prose(text string) string {
	return link.ReplaceAllString(codeSpan.ReplaceAllString(text, " "), " ")
}

// FirstSentence is a text's first sentence as work_tickets.goal_summary takes a Goal's.
func FirstSentence(text string) string {
	text = comment.ReplaceAllString(text, "")
	whole := "\n" + strip(text)
	lead := whole
	if loc := listStart.FindStringIndex(whole); loc != nil {
		lead = whole[:loc[0]]
	}
	if strip(lead) != "" {
		text = joinWords(lead)
	} else {
		text = joinWords(text)
	}
	runes := []rune(text)
	for i := 1; i < len(runes); i++ {
		if isSpace(runes[i]) && strings.ContainsRune(".!?", runes[i-1]) {
			return string(runes[:i])
		}
	}
	return text
}

func quotes(text string) []string {
	text = comment.ReplaceAllString(text, "")
	var found, run []string
	for _, line := range append(splitLines(text, false), "") {
		if m := quoteLine.FindStringSubmatch(line); m != nil {
			run = append(run, m[1])
			continue
		}
		if len(run) > 0 && strip(strings.Join(run, " ")) != "" {
			found = append(found, joinWords(strings.Join(run, " ")))
		}
		run = nil
		for _, m := range quoteSpans.FindAllStringSubmatch(line, -1) {
			q := m[1]
			if q == "" {
				q = m[2]
			}
			found = append(found, joinWords(q))
		}
	}
	var out []string
	for _, q := range found {
		if q != "" {
			out = append(out, q)
		}
	}
	return out
}

func quoted(item *Field, text string, raw *string) []string {
	found := quotes(text)
	head := item.Heading
	if head == "" {
		head = item.Name
	}
	if len(found) == 0 {
		return []string{fmt.Sprintf("%s quotes nothing: quote the raw input word for word, in \"...\" or as a `>` line (or write `%s` where the input does not say)", head, NotInInput)}
	}
	if raw == nil {
		return nil
	}
	held := joinWords(comment.ReplaceAllString(*raw, ""))
	var fixes []string
	for _, q := range found {
		if !strings.Contains(held, q) {
			fixes = append(fixes, fmt.Sprintf("%s quotes \"%s\", which the raw input does not hold: quote it word for word, or drop the quote", head, q))
		}
	}
	return fixes
}

func entryTexts(value any) []string {
	if list, ok := value.([]any); ok {
		var out []string
		for _, entry := range list {
			if wholeComment(str(entry)) {
				continue
			}
			if o, isObject := entry.(Object); isObject {
				text := ""
				if v, has := o.Get("text"); has {
					text = str(v)
				}
				out = append(out, text)
			} else {
				out = append(out, str(entry))
			}
		}
		return out
	}
	var out []string
	for _, line := range splitLines(plainText(value), false) {
		if strip(line) != "" {
			out = append(out, line)
		}
	}
	return out
}

func wordPattern(word string) *regexp.Regexp {
	return regexp.MustCompile(`(?i)\b` + regexp.QuoteMeta(word) + `\b`)
}

// hasBareNumber is the rule bare-number's search: #<digits> not after a letter, a digit, `_`, `/`,
// `&`, `#` or `[`.
func hasBareNumber(text string) bool {
	for _, loc := range bareNumber.FindAllStringIndex(text, -1) {
		if loc[0] == 0 {
			return true
		}
		before := []rune(text[:loc[0]])
		r := before[len(before)-1]
		if !(r == '_' || r == '/' || r == '&' || r == '#' || r == '[' || isWordRune(r)) {
			return true
		}
	}
	return false
}

func isWordRune(r rune) bool {
	return r == '_' || (r >= '0' && r <= '9') || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r > 0x7f && (unicode.IsLetter(r) || unicode.IsDigit(r)))
}

// Check gives every finding of the document against the template, refusals first, in field order.
// raw, the raw input a fill takes, is what a quote field's quotes must hold; nil without one.
//
// A check that fails (an adapter written wrong) answers its error as one refusing finding of the
// field `body`; CheckText answers it as the error it is.
func Check(t *Template, doc *Document, raw *string) []Finding {
	found, err := CheckText(t, doc, raw)
	if err != nil {
		found = append(found, Finding{"body", "checker", Refuse, err.Error()})
	}
	return found
}

// CheckText is Check with the error of a check that fails, as templates.py check raises it.
func CheckText(t *Template, doc *Document, raw *string) ([]Finding, error) {
	if t.IsAdapter() {
		return adapterFindings(t, doc)
	}
	return fieldFindings(t, doc, raw), nil
}

func fieldFindings(t *Template, doc *Document, raw *string) []Finding {
	found := provenance(t, doc)
	add := func(rule, field, fix string) {
		if severity := t.Severity(rule); severity != Off {
			found = append(found, Finding{field, rule, severity, fix})
		}
	}
	values := doc.Fields
	filled := Object{}
	hashes := strings.Repeat("#", t.Level())
	for _, item := range t.Fields {
		if item.Source == "title" && !values.Has(item.Name) {
			continue
		}
		value, present := values.Get(item.Name)
		if notInInput(value) {
			continue
		}
		why := emptiness(item, value, present)
		var where string
		switch {
		case item.Source == "title":
			where = "the title"
		case item.Label != "":
			where = fmt.Sprintf("a `%s:` line", item.Label)
		case item.Fence != "":
			where = fmt.Sprintf("a `%s` fence", item.Fence)
		case t.Message != "":
			where = fmt.Sprintf("the message's {%s}", item.Name)
		default:
			where = fmt.Sprintf("`%s %s`", hashes, item.Heading)
		}
		if miss, missed := doc.Misses[item.Name]; why == "missing" && missed {
			if item.Required {
				add("required", item.Name, fmt.Sprintf("%s is missing: the heading `%s` must be exactly `%s %s`", item.Heading, miss, hashes, item.Heading))
			}
			continue
		}
		if why != "" && item.Required {
			text := map[string]string{"missing": "is missing", "empty": "is empty", "placeholder": "holds a placeholder", "says": "repeats its own description"}[why]
			name := item.Heading
			if name == "" {
				name = item.Label
			}
			if name == "" {
				name = item.Name
			}
			add("required", item.Name, fmt.Sprintf("%s %s: write %s: %s (or `%s` where the input does not say)", name, text, where, item.Says, NotInInput))
			continue
		}
		if why != "" {
			continue
		}
		filled.Set(item.Name, value)
		text := plain(value)
		if holdsSlot(text) {
			name := item.Heading
			if name == "" {
				name = item.Label
			}
			if name == "" {
				name = item.Name
			}
			found = append(found, Finding{item.Name, slotRule, Refuse, fmt.Sprintf("section %s still holds the fill slot %s: write the section in its place", name, slot)})
		}
		if item.Node != "" {
			found = append(found, nestedFindings(item, text, raw)...)
			continue
		}
		if item.Quote {
			for _, fix := range quoted(item, text, raw) {
				found = append(found, Finding{item.Name, quoteRule, Refuse, fix})
			}
		}
		if _, has := item.Cases.Get(strip(text)); item.Kind == "case" && !has {
			keys := make([]string, len(item.Cases))
			for i, pair := range item.Cases {
				keys[i] = pair.Key
			}
			add("choice", item.Name, fmt.Sprintf("%s is %s: write one of %s", item.Name, repr(strip(text)), joinStrings(keys)))
		}
		if item.Kind == "choice" {
			word := casefold(strip(text))
			if loc := choiceSplit.FindStringIndex(word); loc != nil {
				word = word[:loc[0]]
			}
			if !in(word, item.Choices) {
				name := item.Heading
				if name == "" {
					name = item.Label
				}
				add("choice", item.Name, fmt.Sprintf("%s is %s: write one of %s", name, repr(strip(text)), joinStrings(item.Choices)))
			}
		}
		if item.NotPicked && !notPicked.MatchString(comment.ReplaceAllString(text, "")) {
			add("not-picked", item.Name, fmt.Sprintf("%s names no alternative: add a line `Not picked: <what and why not>`", item.Heading))
		}
		if item.MaxWords > 0 {
			if n := len(words(prose(comment.ReplaceAllString(text, "")))); n > item.MaxWords {
				add("words", item.Name, fmt.Sprintf("%s has %d words; keep it to %d", item.Heading, n, item.MaxWords))
			}
		}
		if item.FirstSentenceChars > 0 {
			if n := chars(FirstSentence(text)); n > item.FirstSentenceChars {
				add("first-sentence", item.Name, fmt.Sprintf("%s's first sentence has %d characters; keep it to %d, one complete statement: it becomes the landing title", item.Heading, n, item.FirstSentenceChars))
			}
		}
		if item.Actor && len(t.Actors) > 0 {
			for number, entry := range entryTexts(value) {
				named := false
				for _, actor := range t.Actors {
					if wordPattern(actor).MatchString(entry) {
						named = true
						break
					}
				}
				if !named {
					add("actor", item.Name, fmt.Sprintf("%s item %d names nobody: say who does it (%s)", item.Heading, number+1, joinStrings(t.Actors)))
				}
			}
		}
		if item.OneSentence {
			for number, entry := range entryTexts(value) {
				if sentenceEnd.MatchString(prose(entry)) {
					add("one-sentence", item.Name, fmt.Sprintf("%s item %d has more than one sentence: one sentence per step", item.Heading, number+1))
				}
			}
		}
		if item.Kind == "issue" {
			for _, entry := range entryTexts(value) {
				if bareIssue.MatchString(strip(entry)) {
					add("unnamed-entry", item.Name, fmt.Sprintf("%s entry %s has no name: add what it is, `#12 the templates engine`", item.Heading, strip(entry)))
				}
			}
		}
		if item.Kind != "issue" && item.Kind != "code" && item.Source != "title" {
			if hasBareNumber(prose(text)) {
				add("bare-number", item.Name, fmt.Sprintf("%s names an issue by its number alone: link it or name it in words", item.Heading))
			}
			if board.MatchString(text) {
				add("board", item.Name, fmt.Sprintf("%s repeats the board (Status, Labels, Priority, Assignee, Milestone): leave those to the tracker", item.Heading))
			}
			if !item.Verbatim {
				p := prose(comment.ReplaceAllString(text, ""))
				for _, term := range t.Terms {
					if wordPattern(term.Term).MatchString(p) {
						add("terms", item.Name, fmt.Sprintf("%s uses the inside term %s: say %s", item.Heading, repr(term.Term), term.Plain))
					}
				}
			}
		}
		if item.Source == "title" {
			title(t, item, text, doc, add)
		}
	}
	seen := map[string]string{}
	for _, item := range t.Fields {
		value, ok := filled.Get(item.Name)
		if !ok || item.Source == "title" {
			continue
		}
		key := squash(plain(value))
		if key == "" || strings.TrimRight(key, ".") == noneWord {
			continue
		}
		if first, taken := seen[key]; taken {
			add("duplicate", item.Name, fmt.Sprintf("%s repeats %s word for word: say in each what only it says", item.Heading, first))
		} else {
			name := t.Field(item.Name).Heading
			if name == "" {
				name = item.Name
			}
			seen[key] = name
		}
	}
	found = append(found, fenceOrder(t, doc)...)
	if doc.Source != "" {
		for _, f := range Dangling(doc.Source, seCheckout(), true) {
			add("dangling", fieldAt(doc, f.Line), f.String()+": correct it, or say in Requirements that this issue adds it")
		}
	}
	order := map[string]int{}
	for i, item := range t.Fields {
		order[item.Name] = i
	}
	rank := func(f Finding) (int, int) {
		r := 1
		if f.Severity == Refuse {
			r = 0
		}
		o, ok := order[f.Field]
		if !ok {
			o = len(order)
		}
		return r, o
	}
	sort.SliceStable(found, func(i, j int) bool {
		ri, oi := rank(found[i])
		rj, oj := rank(found[j])
		if ri != rj {
			return ri < rj
		}
		return oi < oj
	})
	return found
}

func title(t *Template, item *Field, text string, doc *Document, add func(rule, field, fix string)) {
	text = strip(text)
	switch rule := item.rule.(type) {
	case *regexp.Regexp:
		if !regexp.MustCompile(`^(?:` + rule.String() + `)\z`).MatchString(text) {
			add("title-shape", item.Name, fmt.Sprintf("the title %s does not match %s: %s", repr(text), item.Shape, item.Says))
		}
	case ShapeFunc:
		if problem := rule(text); problem != "" {
			add("title-shape", item.Name, problem)
		}
	default:
		if pathLike.MatchString(text) || numberTitle.MatchString(text) {
			add("title-shape", item.Name, fmt.Sprintf("the title %s is a branch name, a path or a number: say in plain words what changes", repr(text)))
		}
	}
	var preambles []string
	for _, part := range doc.Parts {
		if part.Kind == "preamble" {
			preambles = append(preambles, part.Raw)
		}
	}
	var others []string
	for _, pair := range doc.Fields {
		if pair.Key != item.Name {
			others = append(others, plain(pair.Value))
		}
	}
	body := squash(strings.Join(preambles, "\n") + "\n" + strings.Join(others, "\n"))
	if text != "" && len(words(text)) >= 3 {
		repeat := regexp.MustCompile(`(?:^|\s)` + regexp.QuoteMeta(squash(text)) + `(?:\s|$)`)
		if repeat.MatchString(body) {
			add("title-shape", item.Name, "the body repeats the title: the title is the GitHub title alone")
		}
	}
}

func nestedFindings(item *Field, text string, raw *string) []Finding {
	nested := item.nested
	checked := func(body string, title *string) []Finding {
		return Check(nested, Parse(nested, body, title), raw)
	}
	under := func(f Finding, where string) Finding {
		return Finding{item.Name, f.Rule, f.Severity, where + ": " + strings.TrimPrefix(f.Fix, nested.Name+": ")}
	}
	var found []Finding
	if item.Kind == "node" {
		for _, f := range checked(text, nil) {
			found = append(found, under(f, nested.Name))
		}
		return found
	}
	listed := registerEntries(text)
	if len(listed) == 0 {
		head := item.Heading
		if head == "" {
			head = item.Name
		}
		return []Finding{{item.Name, nodeRule, Refuse, fmt.Sprintf("%s holds no entry: write each entry as a heading of its own, `### <name>`, then its %s fields", head, nested.Name)}}
	}
	titled := false
	for _, f := range nested.Fields {
		if f.Source == "title" {
			titled = true
			break
		}
	}
	for _, entry := range listed {
		var named *string
		if titled {
			name := entry[0]
			named = &name
		}
		for _, f := range checked(entry[1], named) {
			found = append(found, under(f, fmt.Sprintf("entry %s (%s)", repr(entry[0]), nested.Name)))
		}
	}
	return found
}

// registerEntries are a register's entries, (name, text): each heading at the shallowest level the
// text holds outside its fences, its text up to the next such heading.
func registerEntries(text string) [][2]string {
	type line struct {
		level int
		text  string
	}
	var lines []line
	state := ""
	for _, l := range splitLines(text, true) {
		bare := bareLine(l)
		next, may := fenceStep(state, bare)
		state = next
		level := 0
		if may {
			if m := heading.FindStringSubmatch(bare); m != nil {
				level = len(m[1])
			}
		}
		lines = append(lines, line{level, l})
	}
	top := 0
	for _, l := range lines {
		if l.level > 0 && (top == 0 || l.level < top) {
			top = l.level
		}
	}
	if top == 0 {
		return nil
	}
	var found [][2]string
	for _, l := range lines {
		if l.level == top {
			found = append(found, [2]string{heading.FindStringSubmatch(bareLine(l.text))[2], ""})
		} else if len(found) > 0 {
			found[len(found)-1][1] += l.text
		}
	}
	return found
}

func fenceOrder(t *Template, doc *Document) []Finding {
	var found []Finding
	names := map[string]int{}
	for i, item := range t.Fields {
		names[item.Name] = i
	}
	at := map[string]int{}
	for i, part := range doc.Parts {
		if part.Kind == "field" || part.Kind == "node" {
			at[part.Name] = i
		}
	}
	hashes := strings.Repeat("#", t.Level())
	for _, item := range t.Fields {
		if item.Fence == "" {
			continue
		}
		here, placed := at[item.Name]
		if !placed {
			continue
		}
		for _, other := range t.Fields {
			there, ok := at[other.Name]
			if !other.InBody() || !ok {
				continue
			}
			before := names[other.Name] < names[item.Name]
			if before != (there < here) {
				fix := fmt.Sprintf("`%s %s` comes before the `%s` fence: write it after the fence", hashes, other.Heading, item.Fence)
				if before {
					fix = fmt.Sprintf("`%s %s` comes after the `%s` fence: write it before the fence", hashes, other.Heading, item.Fence)
				}
				found = append(found, Finding{item.Name, nodeRule, Refuse, fix})
			}
		}
	}
	return found
}

func provenance(t *Template, doc *Document) []Finding {
	recorded, current := doc.Recorded, t.Version
	parts, isVersion := versionParts(t, recorded)
	now, _ := versionParts(t, current)
	if recorded == "" || current == "" || recorded == current || isVersion && parts == now {
		return nil
	}
	named := fmt.Sprintf("the document records %s %s; the template is at %s", t.Name, recorded, current)
	where, given := t.Name, " --body-file <file>"
	if t.IsFile() {
		where, given = "--path <file>", ""
	}
	if isVersion && parts[0] == now[0] {
		return []Finding{{"template", versionRule, Warn, fmt.Sprintf("%s, another minor or patch version: render it again to record %s: `templates.py check %s%s --render`", named, current, where, given)}}
	}
	why := "another major version, which the document no longer fits"
	if !isVersion {
		why = fmt.Sprintf("and %s is no semantic version", recorded)
	}
	return []Finding{{"template", versionRule, Refuse, fmt.Sprintf("%s, %s: fill it again at %s: `templates.py draft %s --json` gives its fields, and `templates.py check %s --fields <fields> --render` writes it", named, why, current, where, where)}}
}

// holdsSlot is templates.py `holds_slot`: whether text holds the fill slot outside code, a fence or
// a code span.
func holdsSlot(text string) bool {
	var kept []string
	open := ""
	for _, line := range splitLines(text, false) {
		m := fence.FindStringSubmatch(line)
		switch {
		case open == "" && m != nil:
			open = m[1]
		case open != "":
			if m != nil && strings.HasPrefix(m[1], open) {
				open = ""
			}
		default:
			kept = append(kept, codeSpan.ReplaceAllString(line, ""))
		}
	}
	return strings.Contains(strings.Join(kept, "\n"), slot)
}

// versionParts is templates.py `version_parts`: version as its three whole numbers, ok false where
// it is no version of t's form: a semantic version, or for a template manifest one to three
// numbers, the missing ones 0.
func versionParts(t *Template, version string) ([3]int, bool) {
	form := semver
	if t.Manifest {
		form = manifestVersion
	}
	if !form.MatchString(version) {
		return [3]int{}, false
	}
	var parts [3]int
	for i, part := range strings.Split(version, ".") {
		parts[i], _ = strconv.Atoi(part)
	}
	return parts, true
}

// adapterFindings are an adapter's findings: its lines, its title rule, then its checker's answer
// (checkerFindings); an error is the adapter written wrong, as Python's TemplateError.
func adapterFindings(t *Template, doc *Document) ([]Finding, error) {
	spec, body := t.Adapter, doc.Source
	titleValue, hasTitle := doc.Fields.Get("title")
	var found []Finding
	refuse := func(rule, fix, severity string) {
		found = append(found, Finding{"body", rule, severity, t.Name + ": " + fix})
	}
	var lines []string
	for _, line := range splitLines(body, false) {
		lines = append(lines, strip(line))
	}
	specLines, _ := spec.Value("lines").([]any)
	for _, l := range specLines {
		line := l.(Object)
		pattern := regexp.MustCompile(`^(?:` + str(line.Value("pattern")) + `)\z`)
		held := false
		if truthy(line.Value("first")) {
			held = len(lines) > 0 && pattern.MatchString(lines[0])
		} else {
			for _, text := range lines {
				if pattern.MatchString(text) {
					held = true
					break
				}
			}
		}
		if !held {
			refuse("line", str(line.Value("says")), Refuse)
		}
	}
	if truthy(spec.Value("title_rule")) {
		name := str(spec.Value("title_rule"))
		rule, ok := References[name].(*regexp.Regexp)
		if !ok {
			return found, fail("%s: the Go engine holds no port of %s; check this text with scripts/templates.py", t.Path, name)
		}
		title, _ := titleValue.(string)
		if !hasTitle || !regexp.MustCompile(`^(?:`+rule.String()+`)`).MatchString(title) {
			shown := "None"
			if hasTitle {
				shown = repr(title)
			}
			refuse("title", fmt.Sprintf("the title %s does not match %s (%s)", shown, repr(rule.String()), name), Refuse)
		}
	}
	if t.Checker == "" {
		return found, nil
	}
	return found, checkerFindings(t, body, titleValue, refuse)
}

// Selection is what Select chose: the template (nil: free) and the refused markers it met.
type Selection struct {
	Template *Template
	Findings []Finding
}

// Name is the chosen template's name, "" where the body is free.
func (s Selection) Name() string {
	if s.Template == nil {
		return ""
	}
	return s.Template.Name
}

// Where is what selection reads beside the body: the labels, the pull request's base and the
// integration branch, the repository written to and the repositories SE writes to, a file's path.
type Where struct {
	Labels      []string
	Base        *string
	Integration string
	Repo        *string
	Home        []string
	Path        *string
}

func repositoryName(name string) string {
	return casefold(strings.TrimSuffix(strings.Trim(strip(name), "/"), ".git"))
}

func atHome(repo string, home []string) bool {
	wanted := repositoryName(repo)
	for _, k := range home {
		known := repositoryName(k)
		if wanted == known || (strings.Count(wanted, "/") == 1 && strings.HasSuffix(known, "/"+wanted)) ||
			(strings.Count(known, "/") == 1 && strings.HasSuffix(wanted, "/"+known)) {
			return true
		}
	}
	return false
}

func carries(t *Template, lines map[string]bool) bool {
	if t.Marker != "" && lines[t.Marker] {
		return true
	}
	if t.MarkerPattern == "" {
		return false
	}
	pattern := regexp.MustCompile(`^(?:` + t.MarkerPattern + `)\z`)
	for line := range lines {
		if pattern.MatchString(line) {
			return true
		}
	}
	return false
}

func whyNot(t *Template, action string) string {
	if !in(action, t.Actions) {
		return fmt.Sprintf("the %s template does not apply to %s: it shapes %s", t.Name, action, joinStrings(t.Actions))
	}
	needs := joinStrings(t.Labels)
	if needs == "" {
		needs = "none"
	}
	msg := fmt.Sprintf("the %s template does not apply here: it needs the labels %s", t.Name, needs)
	if t.Base != "" {
		msg += " and a pull request into the integration branch"
	}
	return msg
}

func byOrder(list []*Template) {
	sort.SliceStable(list, func(i, j int) bool {
		if list[i].Order != list[j].Order {
			return list[i].Order < list[j].Order
		}
		return list[i].Name < list[j].Name
	})
}

func strippedLines(body string) map[string]bool {
	lines := map[string]bool{}
	for _, line := range splitLines(body, false) {
		lines[strip(line)] = true
	}
	return lines
}

func conditionsHold(t *Template, lines map[string]bool, title *string) (bool, bool) {
	if t.Marker == "" && t.MarkerPattern == "" && t.TitlePattern == "" {
		return false, false
	}
	if (t.Marker != "" || t.MarkerPattern != "") && !carries(t, lines) {
		return true, false
	}
	if t.TitlePattern != "" {
		text := ""
		if title != nil {
			text = *title
		}
		if !regexp.MustCompile(t.TitlePattern).MatchString(text) {
			return true, false
		}
	}
	return true, true
}

// Select gives the template that shapes body for action (scripts/templates.py's docstring,
// "Selection"); its template nil is free.
func Select(templates Catalog, action, body string, title *string, where Where) (Selection, error) {
	if !in(action, Actions) {
		return Selection{}, fail("select: action %s is none of %s", repr(action), joinStrings(Actions))
	}
	if action == FileAction {
		if where.Path == nil {
			return Selection{}, fail("select: %s selects by the file's path; give path", FileAction)
		}
		return selectFile(templates, body, title, *where.Path), nil
	}
	if where.Repo != nil && where.Home != nil && !atHome(*where.Repo, where.Home) {
		return Selection{}, nil
	}
	integration := where.Integration
	if integration == "" {
		integration = "main"
	}
	have := map[string]bool{}
	for _, label := range where.Labels {
		have[casefold(label)] = true
	}
	allowed := map[string]bool{}
	var candidates []*Template
	for _, name := range sortedKeys(templates) {
		t := templates[name]
		ok := in(action, t.Actions)
		for _, label := range t.Labels {
			if !have[casefold(label)] {
				ok = false
			}
		}
		if t.Base != "" && (where.Base == nil || *where.Base != integration) {
			ok = false
		}
		if ok {
			candidates = append(candidates, t)
			allowed[t.Name] = true
		}
	}
	byOrder(candidates)
	lines := strippedLines(body)
	var refused []Finding
	marked := Object{}
	var markedNames []string
	for _, m := range templateMarkerLine.FindAllStringSubmatch(body, -1) {
		marked.Set(m[1], strip(m[0]))
		markedNames = append(markedNames, m[1])
	}
	for _, pair := range marked {
		if t, ok := templates[pair.Key]; ok && !allowed[pair.Key] {
			refused = append(refused, Finding{"body", "template", Refuse, whyNot(t, action) + fmt.Sprintf("; take out `%s`", str(pair.Value))})
		}
	}
	for _, name := range sortedKeys(templates) {
		t := templates[name]
		if t.IsAdapter() && !allowed[name] && carries(t, lines) {
			refused = append(refused, Finding{"body", "template", Refuse, whyNot(t, action) + ", and the body carries its marker"})
		}
	}
	for _, t := range candidates {
		if in(t.Name, markedNames) {
			return Selection{t, refused}, nil
		}
	}
	for _, t := range candidates {
		if conditioned, hold := conditionsHold(t, lines, title); conditioned && hold {
			return Selection{t, refused}, nil
		}
	}
	for _, t := range candidates {
		if t.Fallback || (t.Marker == "" && t.MarkerPattern == "" && t.TitlePattern == "") {
			return Selection{t, refused}, nil
		}
	}
	return Selection{nil, refused}, nil
}

func selectFile(templates Catalog, body string, title *string, path string) Selection {
	path = strings.Trim(strings.ReplaceAll(path, "\\", "/"), "/")
	var candidates []*Template
	for _, name := range sortedKeys(templates) {
		t := templates[name]
		if in(FileAction, t.Actions) && t.Claims(path) {
			candidates = append(candidates, t)
		}
	}
	byOrder(candidates)
	if len(candidates) == 0 {
		return Selection{}
	}
	var names []string
	for _, t := range candidates {
		names = append(names, t.Name)
	}
	var refused []Finding
	if named, ok := frontMatterTemplate(body); ok {
		for _, t := range candidates {
			if t.Name == named {
				return Selection{Template: t}
			}
		}
		refused = append(refused, Finding{"body", "template", Refuse, fmt.Sprintf("%s: the front matter is derived from template %s, which does not claim this file; name one of %s", path, named, joinStrings(names))})
	}
	lines := strippedLines(body)
	for _, t := range candidates {
		if conditioned, hold := conditionsHold(t, lines, title); conditioned && hold {
			return Selection{t, refused}
		}
	}
	refused = append(refused, Finding{"body", "template", Refuse, fmt.Sprintf("%s: no template takes this file; name its template in the front matter, derived_from: {template: <name>, version: <version>} (one of %s)", path, joinStrings(names))})
	return Selection{nil, refused}
}

// Verdict is the template Select takes for body and every finding: its refused markers, then the
// template's check.
func Verdict(templates Catalog, action, body string, title *string, where Where) (*Template, []Finding, error) {
	chosen, err := Select(templates, action, body, title, where)
	if err != nil {
		return nil, nil, err
	}
	found := append([]Finding{}, chosen.Findings...)
	if chosen.Template != nil {
		checked, err := CheckText(chosen.Template, Parse(chosen.Template, body, title), nil)
		if err != nil {
			return chosen.Template, nil, err
		}
		found = append(found, checked...)
	}
	return chosen.Template, found, nil
}
