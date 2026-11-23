package template

import (
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// The adapters' checkers in Go: the port of each check an adapter names (`checker: <module>:<name>`)
// and of what reads the body for it (`extract`), called as templates.py `adapter_findings` calls the
// Python one. A checker answers what its result is: a list of texts for `problems`, any value for
// `truth`, and for `raises` nothing, its refusal the error. A *fault is the Python error that means
// the adapter is written wrong, never that the text is (templates.py `_MISCONFIGURED`): the check
// fails, naming it, as Python's raises its TemplateError.

// Checker is an adapter's check, called with the value the body gives and the keywords the adapter
// sets.
type Checker func(value any, keywords map[string]any) (any, error)

// Extractor reads an adapter's value from the body, with the adapter's `extract_with`.
type Extractor func(body string, keywords map[string]any) (any, error)

// Checkers are the adapters' checks the Go engine holds, by the name the template gives.
var Checkers = map[string]Checker{
	"deck:pugh_problems":                 func(v any, _ map[string]any) (any, error) { return pughProblems(str(v)), nil },
	"work_tickets:field_report_problems": fieldReportChecker,
	"work_tickets:merge_release_kind":    mergeReleaseKind,
	"review:checked_report":              checkedReport,
	"retro:judgment_problems":            retroJudgmentProblems,
	"overhaul:judgment_problems":         overhaulJudgmentProblems,
}

// Extractors are the readings an adapter's `extract` names.
var Extractors = map[string]Extractor{
	"work_tickets:report_in": func(body string, kw map[string]any) (any, error) {
		return reportIn(body, str(kw["where"]))
	},
}

// refusal is a Python check's own refusal, such as a QueueError: its text is the finding's fix.
type refusal struct{ msg string }

func (r *refusal) Error() string { return r.msg }

func refuseWith(format string, args ...any) error { return &refusal{fmt.Sprintf(format, args...)} }

// fault is a Python error templates.py counts as a misconfigured adapter (TypeError, AttributeError
// and their kin): its type and its text.
type fault struct{ kind, msg string }

func (f *fault) Error() string { return f.kind + ": " + f.msg }

func pyType(v any) string {
	switch v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case int, *big.Int:
		return "int"
	case float64:
		return "float"
	case string:
		return "str"
	case []any:
		return "list"
	case Object:
		return "dict"
	}
	return fmt.Sprintf("%T", v)
}

// get is Python's value.get(key): a fault where the value is no dict.
func get(v any, key string) (any, error) {
	o, ok := v.(Object)
	if !ok {
		return nil, &fault{"AttributeError", fmt.Sprintf("'%s' object has no attribute 'get'", pyType(v))}
	}
	return o.Value(key), nil
}

// iterate is Python's `for item in value`: a list's items, a dict's keys, a text's characters.
func iterate(v any) ([]any, error) {
	switch x := v.(type) {
	case []any:
		return x, nil
	case Object:
		keys := make([]any, len(x))
		for i, pair := range x {
			keys[i] = pair.Key
		}
		return keys, nil
	case string:
		var found []any
		for _, r := range x {
			found = append(found, string(r))
		}
		return found, nil
	}
	return nil, &fault{"TypeError", fmt.Sprintf("'%s' object is not iterable", pyType(v))}
}

// pyWords is review.py `words`: a text stripped, "" for anything else.
func pyWords(v any) string {
	if s, ok := v.(string); ok {
		return strip(s)
	}
	return ""
}

func isBool(v any) bool { _, ok := v.(bool); return ok }

// unknownKeys is sorted(set(given) - set(known)).
func unknownKeys(given Object, known ...string) []string {
	var extra []string
	for _, pair := range given {
		if !in(pair.Key, known) && !in(pair.Key, extra) {
			extra = append(extra, pair.Key)
		}
	}
	sort.Strings(extra)
	return extra
}

// The reading of an adapter's body.

// jsonAfter is templates.py `_json_after`: the data of the last fenced block after the last line
// that is the marker; nil, false without the marker.
func jsonAfter(body, marker string) (any, bool, error) {
	lines := splitLines(body, true)
	at := -1
	for i, line := range lines {
		if strip(line) == marker {
			at = i
		}
	}
	if at < 0 {
		return nil, false, nil
	}
	rest := strings.Join(lines[at+1:], "")
	blocks := fencedBlocks(rest)
	if len(blocks) == 0 {
		return nil, true, refuseWith("the %s block has no fenced block under it", marker)
	}
	v, err := pyJSON(blocks[len(blocks)-1])
	if err != nil {
		return nil, true, refuseWith("the %s block is not JSON: %s", marker, err)
	}
	return v, true, nil
}

// fencedBlocks are the contents of `^(`{3,})[^\n]*\n(.*?)^\1[ \t]*$` (MULTILINE, DOTALL), as
// re.findall gives them.
func fencedBlocks(text string) []string {
	var found []string
	lineStart := func(i int) bool { return i == 0 || text[i-1] == '\n' }
	for p := 0; p < len(text); {
		if !lineStart(p) || !strings.HasPrefix(text[p:], "```") {
			p++
			continue
		}
		run := 0
		for p+run < len(text) && text[p+run] == '`' {
			run++
		}
		newline := strings.IndexByte(text[p:], '\n')
		matched := false
		if newline >= 0 {
			start := p + newline + 1
			for n := run; n >= 3 && !matched; n-- {
				open := strings.Repeat("`", n)
				for q := start; q <= len(text); q++ {
					if !lineStart(q) && q != start {
						continue
					}
					if !strings.HasPrefix(text[q:], open) {
						continue
					}
					end := q + n
					for end < len(text) && (text[end] == ' ' || text[end] == '\t') {
						end++
					}
					if end == len(text) || text[end] == '\n' {
						found = append(found, text[start:q])
						p, matched = end, true
						break
					}
				}
			}
		}
		if !matched {
			p++
		}
	}
	return found
}

// dropped is templates.py `_dropped`: the value without the keys drop names, "." its own, a key its
// list's items'.
func dropped(v any, drop Object) any {
	o, ok := v.(Object)
	if !ok {
		return v
	}
	o = o.Copy()
	for _, pair := range drop {
		names := stringsOf(pair.Value)
		if pair.Key == "." {
			var kept Object
			for _, item := range o {
				if !in(item.Key, names) {
					kept = append(kept, item)
				}
			}
			if kept == nil {
				kept = Object{}
			}
			o = kept
			continue
		}
		list, ok := o.Value(pair.Key).([]any)
		if !ok {
			continue
		}
		entries := make([]any, len(list))
		for i, entry := range list {
			if e, ok := entry.(Object); ok {
				kept := Object{}
				for _, item := range e {
					if !in(item.Key, names) {
						kept = append(kept, item)
					}
				}
				entries[i] = kept
			} else {
				entries[i] = entry
			}
		}
		o.Set(pair.Key, entries)
	}
	return o
}

// checkerFindings is the checker part of templates.py `adapter_findings`, after the lines and the
// title rule: read the value as the adapter says, call the checker, and refuse with what it answers.
// An error is the adapter written wrong (Python's TemplateError), or a reading Go holds no port of.
func checkerFindings(t *Template, body string, title any, refuse func(rule, fix, severity string)) error {
	spec := t.Adapter
	noPort := func(name string) error {
		return fail("%s: the Go engine holds no port of %s; check this text with scripts/templates.py", t.Path, name)
	}
	checker, held := Checkers[t.Checker]
	if !held {
		return noPort(t.Checker)
	}
	var value any
	var err error
	present := true
	marker := str(spec.Value("json_after"))
	switch {
	case truthy(spec.Value("extract")):
		name := str(spec.Value("extract"))
		extract, ok := Extractors[name]
		if !ok {
			return noPort(name)
		}
		kw := map[string]any{}
		if with, ok := spec.Value("extract_with").(Object); ok {
			for _, pair := range with {
				kw[pair.Key] = pair.Value
			}
		}
		value, err = extract(body, kw)
	case truthy(spec.Value("json_after")):
		value, present, err = jsonAfter(body, marker)
	case truthy(spec.Value("sections")):
		return noPort("adapter.sections")
	default:
		value = body
	}
	if f, ok := err.(*fault); ok {
		return fail("%s: its reading failed (%s); fix its adapter", t.Path, f)
	}
	if err != nil {
		refuse("checker", err.Error(), Refuse)
		return nil
	}
	if !present || value == nil {
		missing := Refuse
		if m, ok := spec.Value("missing").(string); ok {
			missing = m
		}
		if missing != "pass" {
			what := ""
			if truthy(spec.Value("json_after")) {
				what = " (no " + marker + " block)"
			}
			refuse("checker", fmt.Sprintf("the body holds nothing for %s to check%s", t.Checker, what), missing)
		}
		return nil
	}
	if drop, ok := spec.Value("drop").(Object); ok {
		value = dropped(value, drop)
	}
	if truthy(spec.Value("when")) {
		return noPort(str(spec.Value("when")))
	}
	kw := map[string]any{}
	if with, ok := spec.Value("with").(Object); ok {
		for _, pair := range with {
			kw[pair.Key] = pair.Value
		}
	}
	for _, name := range stringsOf(spec.Value("none")) {
		kw[name] = nil
	}
	if as := str(spec.Value("title_as")); truthy(spec.Value("title_as")) {
		if s, ok := title.(string); ok && s != "" {
			kw[as] = s
		} else {
			kw[as] = ""
		}
	}
	if as := str(spec.Value("text_as")); truthy(spec.Value("text_as")) {
		kw[as], value = value, nil
	}
	result := "problems"
	if r, ok := spec.Value("result").(string); ok {
		result = r
	}
	answer, err := checker(value, kw)
	if f, ok := err.(*fault); ok {
		return fail("%s: %s failed (%s); fix its adapter", t.Path, t.Checker, f)
	}
	if err != nil {
		if result != "raises" {
			return fail("%s: %s raised %s", t.Path, t.Checker, err)
		}
		refuse("checker", err.Error(), Refuse)
		return nil
	}
	switch result {
	case "problems":
		if list, ok := answer.([]string); ok {
			for _, problem := range list {
				refuse("checker", problem, Refuse)
			}
		}
	case "truth":
		if !truthy(answer) {
			refuse("checker", str(spec.Value("refusal")), Refuse)
		}
	}
	return nil
}

// work_tickets.py: the field report and the integration's squash commit.

const (
	fieldReportTemplate = ".github/pull_request_template.md"
	reportBegin         = "<!-- se:field-report -->"
	reportEnd           = "<!-- se:field-report:end -->"
	removedSection      = "Removed behaviour, deleted or weakened tests, and authored prose"
	releaseTrailer      = "Release-kind"
	releaseTrailerHelp  = "work_tickets.py release-trailer <branch> --issue-body <file> --pr-description <file> prints it from the field report in the pull request description"
	// pyS is Python's `\s` in a str pattern; pyNotS its `\S`.
	pyS    = `[\t-\r\x1c-\x20\x85\p{Z}]`
	pyNotS = `[^\t-\r\x1c-\x20\x85\p{Z}]`
)

var (
	releaseOrder         = []string{"patch", "minor", "major"}
	fieldReportTemplateN = "the se checkout's " + fieldReportTemplate
	htmlComment          = regexp.MustCompile(`(?s)<!--.*?-->`)
	sectionLine          = regexp.MustCompile(`^##` + pyS + `+(.+?)` + pyS + `*$`)
	resultLine           = regexp.MustCompile(`\*\*Result:\*\*` + pyS + `*(complete|partial)` + pyS + `*(?:\n|$)`)
	reintegrationKind    = regexp.MustCompile(`\*\*Re-integration kind:\*\*[ \t]*([^\t-\r\x1c-\x20\x85\p{Z}<]*)`)
	releaseKind          = regexp.MustCompile(`\*\*Release kind:\*\*[ \t]*([\p{L}\p{N}_]*)[ \t]*[—–:,-]*[ \t]*([^\n]*)`)
	componentKinds       = regexp.MustCompile(`\*\*Component kinds:\*\*[ \t]*([^\n<]*)`)
	breakingLine         = regexp.MustCompile(`^` + pyS + `*(?:[-*+]` + pyS + `+)?\*\*Breaking:\*\*`)
	boldLabel            = regexp.MustCompile(`\*\*([^*\n]+?:)\*\*`)
	angleName            = regexp.MustCompile(`<[^<>\n]+>`)
	headerPlaceholder    = regexp.MustCompile(`#?<[^<>\n]+>`)
	firstSection         = regexp.MustCompile(`(?m)^## `)
	trailerLine          = regexp.MustCompile(`(?m)^` + releaseTrailer + `:[ \t]*(` + pyNotS + `*)[ \t]*$`)
)

// reportIn is work_tickets.py `report_in`: the field report between the markers.
func reportIn(text, where string) (string, error) {
	begin := strings.Index(text, reportBegin)
	end := -1
	if begin >= 0 {
		if at := strings.Index(text[begin+len(reportBegin):], reportEnd); at >= 0 {
			end = begin + len(reportBegin) + at
		}
	}
	if begin < 0 || end < 0 {
		return "", refuseWith("%s holds no field report: the report goes between the lines %s and %s of the pull request description, as %s has them; field-report --draft --worktree <worktree> writes them",
			where, reportBegin, reportEnd, fieldReportTemplateN)
	}
	return strings.Trim(text[begin+len(reportBegin):end], "\n") + "\n", nil
}

type section struct {
	heading string
	lines   []string
}

// orderedSections is work_tickets.py `ordered_sections`: the `## ` sections outside code fences.
func orderedSections(body string) []section {
	sections := []section{{"", nil}}
	fenced := false
	for _, line := range splitLines(body, false) {
		if strings.HasPrefix(lstrip(line), "```") {
			fenced = !fenced
		}
		var m []string
		if !fenced {
			m = sectionLine.FindStringSubmatch(line)
		}
		if m != nil {
			sections = append(sections, section{strip(m[1]), nil})
		} else {
			sections[len(sections)-1].lines = append(sections[len(sections)-1].lines, line)
		}
	}
	return sections
}

// tableCells is work_tickets.py `table_cells`: a row's cells, an escaped pipe inside its cell.
func tableCells(line string) []string {
	line = strings.Trim(strip(line), "|")
	var cells []string
	start := 0
	for i := 0; i < len(line); i++ {
		if line[i] == '|' && (i == 0 || line[i-1] != '\\') {
			cells = append(cells, strip(line[start:i]))
			start = i + 1
		}
	}
	return append(cells, strip(line[start:]))
}

func labelPattern(label string) *regexp.Regexp {
	parts := angleName.Split(label, -1)
	for i, part := range parts {
		parts[i] = regexp.QuoteMeta(part)
	}
	return regexp.MustCompile(`\*\*` + strings.Join(parts, `[^*\n]+?`) + `\*\*`)
}

func tableProblems(where, templateHeader, text string) []string {
	width := len(tableCells(templateHeader))
	var rows []string
	for _, line := range splitLines(text, false) {
		if strings.HasPrefix(strip(line), "|") {
			rows = append(rows, strip(line))
		}
	}
	if len(rows) == 0 {
		return []string{fmt.Sprintf("%s: missing its table; the template's header row: %s", where, templateHeader)}
	}
	var problems []string
	got, want := tableCells(rows[0]), tableCells(templateHeader)
	same := len(got) == len(want)
	for i := 0; same && i < len(got); i++ {
		same = casefold(got[i]) == casefold(want[i])
	}
	if !same {
		problems = append(problems, fmt.Sprintf("%s: table header %s does not match the template's %s", where, rows[0], templateHeader))
	}
	for _, row := range rows[1:] {
		if n := len(tableCells(row)); n != width {
			problems = append(problems, fmt.Sprintf("%s: table row %s has %d columns; the template's table has %d: %s", where, row, n, width, templateHeader))
		}
	}
	return problems
}

// fieldReportProblems is work_tickets.py `field_report_problems` without the work issue (the
// template engine passes issue_body None) and without a version: the report's structure against
// SE's pull request template, the one owner of its template.
func fieldReportProblems(body string) ([]string, error) {
	data, err := os.ReadFile(filepath.Join(seCheckout(), filepath.FromSlash(fieldReportTemplate)))
	if err != nil {
		return nil, refuseWith("Field-report template not found: %s: %v", fieldReportTemplateN, err)
	}
	template, err := reportIn(string(data), fieldReportTemplateN)
	if err != nil {
		return nil, err
	}
	report := map[string][]string{}
	for _, s := range orderedSections(body) {
		report[casefold(s.heading)] = s.lines
	}
	var problems []string
	for _, s := range orderedSections(template) {
		where := fmt.Sprintf("section \"## %s\"", s.heading)
		if s.heading == "" {
			where = "header (above the first section)"
		}
		lines, ok := report[casefold(s.heading)]
		if !ok {
			problems = append(problems, fmt.Sprintf("missing %s; the template has the heading \"## %s\"", where, s.heading))
			continue
		}
		text := htmlComment.ReplaceAllString(strings.Join(lines, "\n"), "")
		raw := strings.Join(s.lines, "\n")
		expected := splitLines(htmlComment.ReplaceAllString(raw, ""), false)
		if strings.Contains(raw, `"None"`) && casefold(strings.TrimRight(strip(text), ".")) == "none" {
			continue
		}
		for _, line := range expected {
			for _, m := range boldLabel.FindAllStringSubmatch(line, -1) {
				if !labelPattern(m[1]).MatchString(text) {
					problems = append(problems, fmt.Sprintf("%s: missing \"**%s**\"; the template's line: %s", where, m[1], strip(line)))
				}
			}
		}
		for _, line := range expected {
			if strings.HasPrefix(strip(line), "|") {
				problems = append(problems, tableProblems(where, strip(line), text)...)
				break
			}
		}
	}
	header := strings.Join(report[""], "\n")
	templateHeader := firstSection.Split(htmlComment.ReplaceAllString(template, ""), 2)[0]
	var seen []string
	for _, placeholder := range headerPlaceholder.FindAllString(templateHeader, -1) {
		if in(placeholder, seen) {
			continue
		}
		seen = append(seen, placeholder)
		if strings.Contains(header, placeholder) && placeholder != "<tip>" {
			problems = append(problems, fmt.Sprintf("header (above the first section): unfilled placeholder %s; replace it with its value", placeholder))
		}
	}
	if !hasBranchTip(header) {
		problems = append(problems, "header (above the first section): Branch tip must be the branch's commit; field-report --check --worktree <worktree> fills it from the branch")
	}
	problems = append(problems, releaseKindProblems(body)...)
	problems = append(problems, kindsProblems(body)...)
	if m := reintegrationKind.FindStringSubmatch(header); m != nil && !in(m[1], releaseOrder) {
		problems = append(problems, fmt.Sprintf("header (above the first section): Re-integration kind %s must be one of %s", repr(m[1]), joinStrings(releaseOrder)))
	}
	if !resultLine.MatchString(header) {
		problems = append(problems, `header (above the first section): Result must be exactly complete or partial, as "**Result:** complete" or "**Result:** partial"`)
	}
	return problems, nil
}

func fieldReportChecker(v any, kw map[string]any) (any, error) {
	if kw["issue_body"] != nil {
		return nil, &fault{"NotImplementedError", "the Go engine checks a field report without its work issue"}
	}
	return fieldReportProblems(str(v))
}

// hasBranchTip is work_tickets.py BRANCH_TIP_PATTERN's search,
// `\*\*Branch tip:\*\*[ \t]*`?([0-9a-f]{7,40})`?(?=[ \t]|$)` with MULTILINE.
func hasBranchTip(text string) bool {
	const label = "**Branch tip:**"
	for at := 0; ; {
		i := strings.Index(text[at:], label)
		if i < 0 {
			return false
		}
		p := at + i + len(label)
		at = at + i + 1
		for p < len(text) && (text[p] == ' ' || text[p] == '\t') {
			p++
		}
		if p < len(text) && text[p] == '`' {
			p++
		}
		n := 0
		for p+n < len(text) && (text[p+n] >= '0' && text[p+n] <= '9' || text[p+n] >= 'a' && text[p+n] <= 'f') {
			n++
		}
		if n < 7 || n > 40 {
			continue
		}
		p += n
		ends := func(i int) bool { return i == len(text) || text[i] == ' ' || text[i] == '\t' || text[i] == '\n' }
		if ends(p) || text[p] == '`' && ends(p+1) {
			return true
		}
	}
}

// releaseKindProblems is work_tickets.py `release_kind_problems` without the work issue and
// without a version, where a breaking change takes minor.
func releaseKindProblems(body string) []string {
	header := htmlComment.ReplaceAllString(strings.Join(orderedSections(body)[0].lines, "\n"), "")
	where := "header (above the first section): Release kind"
	m := releaseKind.FindStringSubmatch(header)
	if m == nil {
		return []string{where + " is missing; write **Release kind:** patch|minor|major — <reason>, what changed decides it (work model, Release kind)"}
	}
	kind, reason := m[1], strip(m[2])
	var problems []string
	if !in(kind, releaseOrder) {
		problems = append(problems, fmt.Sprintf("%s %s must be one of %s", where, repr(kind), joinStrings(releaseOrder)))
	}
	if reason == "" {
		problems = append(problems, where+" needs a one-line reason after the kind")
	}
	if kind == "patch" {
		removed := htmlComment.ReplaceAllString(strings.Join(sectionContent(body, removedSection), "\n"), "")
		for _, line := range splitLines(removed, false) {
			if breakingLine.MatchString(line) {
				problems = append(problems, fmt.Sprintf("%s is %s, but section \"## %s\" lists a breaking change, which is minor below 1.0.0: %s", where, kind, removedSection, strip(line)))
			}
		}
	}
	return problems
}

// sectionContent is work_tickets.py `section_content`: the lines under each heading that starts
// with the name.
func sectionContent(content, name string) []string {
	var selected []string
	active := false
	for _, line := range splitLines(content, false) {
		if m := sectionLine.FindStringSubmatch(line); m != nil {
			active = strings.HasPrefix(casefold(strip(m[1])), casefold(name))
			continue
		}
		if active {
			selected = append(selected, line)
		}
	}
	return selected
}

// kindsProblems is component_versions.py `kinds_problems`.
func kindsProblems(body string) []string {
	header := firstSection.Split(htmlComment.ReplaceAllString(body, ""), 2)[0]
	m := componentKinds.FindStringSubmatch(header)
	if m == nil {
		return nil
	}
	value, _, _ := strings.Cut(m[1], " — ")
	for _, part := range strings.Split(value, ",") {
		entry := strip(part)
		if entry == "" {
			continue
		}
		parts := words(entry)
		if len(parts) != 2 || !in(parts[1], releaseOrder) {
			return []string{fmt.Sprintf("header (above the first section): Component kinds entry %s is no <component> patch|minor|major; write **Component kinds:** <component> patch|minor|major, comma-separated, as se patch", repr(entry))}
		}
	}
	return nil
}

// oneLine is work_tickets.py `one_line`.
func oneLine(text string) string {
	line := strings.ReplaceAll(strings.Join(words(text), " "), "**", "")
	runes := []rune(line)
	if len(runes) <= 90 {
		return line
	}
	cut := string(runes[:87])
	if i := strings.LastIndex(cut, " "); i >= 0 {
		cut = cut[:i]
	}
	return cut + "..."
}

// mergeReleaseKind is work_tickets.py `merge_release_kind`: the merge states one release kind in
// its trailer, or it is refused.
func mergeReleaseKind(_ any, kw map[string]any) (any, error) {
	commit, subject, message := str(kw["commit"]), str(kw["subject"]), str(kw["message"])
	var kinds []string
	for _, m := range trailerLine.FindAllStringSubmatch(message, -1) {
		kinds = append(kinds, m[1])
	}
	if len(kinds) == 1 && in(kinds[0], releaseOrder) {
		return kinds[0], nil
	}
	stated := "states no kind"
	if len(kinds) > 0 {
		shown := make([]string, len(kinds))
		for i, kind := range kinds {
			shown[i] = repr(kind)
		}
		stated = "states " + strings.Join(shown, ", ")
	}
	if r := []rune(commit); len(r) > 7 {
		commit = string(r[:7])
	}
	return nil, refuseWith("Cannot release merge %s (%s): it %s; nothing was written. Before it lands, reword the merge to end with one trailer %s: %s, as %s; one already on the integration branch stays as it is: set project.version by hand in a pull request, which the release then tags as it is",
		commit, oneLine(subject), stated, releaseTrailer, "major|minor|patch", releaseTrailerHelp)
}

// review.py: the review report.

var (
	reviewVerdicts    = []string{"pass", "pass with open points", "decline"}
	reportFields      = []string{"verdict", "head", "acceptance", "findings", "clean"}
	acceptanceFields  = []string{"item", "evidence"}
	reviewFindingKeys = []string{"title", "evidence", "place", "blocking", "why"}
	fullCommit        = regexp.MustCompile(`^[0-9a-f]{40}$`)
)

func unknownField(given Object, known []string, where string) error {
	if extra := unknownKeys(given, known...); len(extra) > 0 {
		return refuseWith("%s has the unknown field %s; it holds only %s", where, extra[0], joinStrings(known))
	}
	return nil
}

// checkedReport is review.py `checked_report`: every refusal of the report, the first one raised.
func checkedReport(given any, _ map[string]any) (any, error) {
	report, ok := given.(Object)
	if !ok {
		return nil, refuseWith("The report is a JSON object with the fields %s", joinStrings(reportFields))
	}
	if err := unknownField(report, reportFields, "The report"); err != nil {
		return nil, err
	}
	verdict := report.Value("verdict")
	v, _ := verdict.(string)
	if !in(v, reviewVerdicts) || !isString(verdict) {
		return nil, refuseWith("The report's verdict is pass, pass with open points or decline, not %s", repr(verdict))
	}
	if !fullCommit.MatchString(pyWords(report.Value("head"))) {
		return nil, refuseWith("The report names no head: the full commit the brief named, which the review checked")
	}
	clean, ok := report.Value("clean").([]any)
	allWords := ok && len(clean) > 0
	for _, entry := range clean {
		allWords = allWords && pyWords(entry) != ""
	}
	if !allWords {
		return nil, refuseWith(`The report has no "checked and clean" list, or an empty entry in it: name what was examined and found sound, the evidence for the verdict`)
	}
	acceptance, ok := report.Value("acceptance").([]any)
	if !ok || len(acceptance) == 0 {
		return nil, refuseWith("The report names no acceptance item: give each acceptance item of the work issue with its evidence")
	}
	var lacking []string
	for _, e := range acceptance {
		entry, ok := e.(Object)
		if !ok {
			return nil, refuseWith("An acceptance item is an object with item and evidence")
		}
		if err := unknownField(entry, acceptanceFields, "An acceptance item"); err != nil {
			return nil, err
		}
		item := pyWords(entry.Value("item"))
		if item == "" {
			return nil, refuseWith("An acceptance item needs its item")
		}
		if pyWords(entry.Value("evidence")) == "" {
			lacking = append(lacking, item)
		}
	}
	findings, ok := report.Value("findings").([]any)
	if !ok {
		return nil, refuseWith("The report's findings are a list (empty where none was found)")
	}
	blocking := 0
	for _, e := range findings {
		entry, ok := e.(Object)
		if !ok {
			return nil, refuseWith("A finding is an object with %s", joinStrings(reviewFindingKeys))
		}
		if err := unknownField(entry, reviewFindingKeys, "A finding"); err != nil {
			return nil, err
		}
		title := pyWords(entry.Value("title"))
		if title == "" {
			return nil, refuseWith("A finding needs its title")
		}
		if pyWords(entry.Value("evidence")) == "" {
			return nil, refuseWith(`The finding "%s" has no evidence: a verified finding has a file and line, or a command and its output; drop what is unproven`, title)
		}
		if pyWords(entry.Value("place")) == "" {
			return nil, refuseWith(`The finding "%s" names no place: the file and line, or the command, where it shows`, title)
		}
		block, isBlock := entry.Value("blocking").(bool)
		if !isBlock || pyWords(entry.Value("why")) == "" {
			return nil, refuseWith(`The finding "%s" has no judgment: blocking true or false, and why (only damage blocks: the product made worse, or against what it is about)`, title)
		}
		if block {
			blocking++
		}
	}
	if v == "decline" {
		if blocking == 0 {
			return nil, refuseWith("A decline needs the evidence that the change is fundamentally wrong: a verified blocking finding; this report has none")
		}
		return nil, nil
	}
	if len(lacking) > 0 {
		return nil, refuseWith(`A %s lands the change, so every acceptance item needs its evidence, and "%s" has none`, v, lacking[0])
	}
	if blocking > 0 {
		return nil, refuseWith("A blocking finding means the change does not land: this report has %d, so its verdict is decline", blocking)
	}
	if v == "pass" && len(findings) > 0 {
		return nil, refuseWith("A pass lands the change as is, and this report has %d finding(s) to address: its verdict is pass with open points", len(findings))
	}
	if v == "pass with open points" && len(findings) == 0 {
		return nil, refuseWith("A pass with open points lists its open points as findings, and this report has none: its verdict is pass")
	}
	return nil, nil
}

func isString(v any) bool { _, ok := v.(string); return ok }

// retro.py and overhaul.py: the judged block.

const (
	titleWords = 5
	ruleBook   = "src/skills/work-model/references/rules.md"
	newRule    = "new"
)

var (
	retroFindingFields    = []string{"title", "body", "class", "home", "controversial", "why", "check"}
	classFields           = []string{"name", "fix"}
	classKeys             = []string{"status", "pattern", "limits"}
	retroJudgment         = []string{"findings", "classes", "went_well"}
	ruleChecks            = []string{"work-issue", "check", "outside-pr", "field-report"}
	verdictFields         = []string{"rule", "strays", "how"}
	strays                = []string{"none", "slightly", "far"}
	lookedAt              = []string{"outside", "consistency", "rules", "retro", "speed", "mechanize", "removal"}
	overhaulFindingFields = []string{"title", "body", "rule", "place", "controversial", "why", "sources"}
)

// findingBasics is retro.py `finding_basics`.
func findingBasics(given Object, index int, fields []string) (string, []string) {
	title := pyWords(given.Value("title"))
	name := fmt.Sprintf("finding %d", index)
	if title != "" {
		name = fmt.Sprintf("finding %d (\"%s\")", index, title)
	}
	var problems []string
	if extra := unknownKeys(given, fields...); len(extra) > 0 {
		problems = append(problems, fmt.Sprintf("%s has the unknown field %s", name, extra[0]))
	}
	if len(words(title)) < titleWords {
		problems = append(problems, fmt.Sprintf("%s needs a title of %d words or more that names the fix", name, titleWords))
	}
	if pyWords(given.Value("body")) == "" {
		problems = append(problems, name+" has no body")
	}
	return name, problems
}

// pythonOnly finds what Python's re reads and Go's regexp does not: look-arounds, back references,
// comments, conditionals, atomic groups and possessive repeats. A pattern Go refuses that holds one
// is taken as Python's to judge, so it passes.
var pythonOnly = regexp.MustCompile(`\(\?(?:=|!|<=|<!|P=|#|\(|>)|\\[1-9]|[*+?}]\+`)

// classKeyProblems is retro.py `class_key_problems`. A pattern is read as Go's regexp reads it:
// one Go refuses is refused with Go's error, where Python names its own (components/README.md).
func classKeyProblems(given Object, name string) []string {
	var problems []string
	if status, ok := given.Get("status"); ok {
		if s, isText := status.(string); !isText || strip(s) == "" {
			problems = append(problems, name+": status is a text")
		}
	}
	if pattern, ok := given.Get("pattern"); ok {
		if p, isText := pattern.(string); !isText || p == "" {
			problems = append(problems, name+": pattern is a regular expression, as a text")
		} else if _, err := regexp.Compile(p); err != nil && !pythonOnly.MatchString(p) {
			problems = append(problems, fmt.Sprintf("%s: pattern is no regular expression (%v)", name, err))
		}
	}
	if limits, ok := given.Get("limits"); ok {
		texts := isString(limits)
		if list, isList := limits.([]any); isList {
			texts = true
			for _, entry := range list {
				texts = texts && isString(entry)
			}
		}
		if !texts {
			problems = append(problems, name+": limits is a text or a list of texts")
		}
	}
	return problems
}

func retroJudgmentProblems(v any, _ map[string]any) (any, error) {
	lists := map[string][]any{}
	var problems []string
	for _, name := range retroJudgment {
		value, err := get(v, name)
		if err != nil {
			return nil, err
		}
		list, ok := value.([]any)
		if !ok {
			problems = append(problems, fmt.Sprintf("`%s` is not a list", name))
		}
		lists[name] = list
	}
	if len(problems) > 0 {
		return problems, nil
	}
	block := v.(Object)
	classes := map[string]bool{}
	for i, g := range lists["classes"] {
		index := i + 1
		given, ok := g.(Object)
		if !ok {
			problems = append(problems, fmt.Sprintf("class %d is not an object with %s", index, joinStrings(classFields)))
			continue
		}
		extra := unknownKeys(given, append(append([]string{}, classFields...), classKeys...)...)
		name := pyWords(given.Value("name"))
		if len(extra) > 0 {
			problems = append(problems, fmt.Sprintf("class %d has the unknown field %s", index, extra[0]))
		}
		label := fmt.Sprintf("class %d", index)
		if name != "" {
			label = fmt.Sprintf("class \"%s\"", name)
		}
		problems = append(problems, classKeyProblems(given, label)...)
		if name == "" {
			problems = append(problems, fmt.Sprintf("class %d has no name", index))
		} else if pyWords(given.Value("fix")) == "" {
			problems = append(problems, fmt.Sprintf("class \"%s\" has no fix", name))
		}
		classes[name] = true
	}
	recurred := map[string]bool{}
	previous := block.Value("previous")
	if !truthy(previous) {
		previous = Object{}
	}
	earlier, err := get(previous, "findings")
	if err != nil {
		return nil, err
	}
	if !truthy(earlier) {
		earlier = []any{}
	}
	items, err := iterate(earlier)
	if err != nil {
		return nil, err
	}
	for _, it := range items {
		item, ok := it.(Object)
		if !ok || !truthy(item.Value("recurred")) {
			continue
		}
		switch check := item.Value("check").(type) {
		case []any, Object:
			return nil, &fault{"TypeError", fmt.Sprintf("unhashable type: '%s'", pyType(check))}
		case string:
			recurred[check] = true
		}
	}
	for i, g := range lists["findings"] {
		index := i + 1
		given, ok := g.(Object)
		if !ok {
			problems = append(problems, fmt.Sprintf("finding %d is not an object with %s", index, joinStrings(retroFindingFields)))
			continue
		}
		name, found := findingBasics(given, index, retroFindingFields)
		problems = append(problems, found...)
		kind := pyWords(given.Value("class"))
		if kind == "" {
			problems = append(problems, name+" has no class")
		} else if !classes[kind] {
			problems = append(problems, fmt.Sprintf("%s names the class \"%s\", which `classes` does not", name, kind))
		}
		home := pyWords(given.Value("home"))
		if home == "" {
			problems = append(problems, name+" has no home: the file it changes")
		}
		controversial, held := given.Get("controversial")
		if !held {
			controversial = false
		}
		if !isBool(controversial) {
			problems = append(problems, name+": controversial is true or false")
		}
		check := pyWords(given.Value("check"))
		if check != "" && !in(check, ruleChecks) {
			problems = append(problems, fmt.Sprintf("%s names the check \"%s\", which is no rule check (%s)", name, check, joinStrings(ruleChecks)))
		}
		sure := controversial == true
		switch {
		case home == ruleBook && !sure:
			problems = append(problems, name+" changes a rule (its home is the rule book), so it is controversial, with its why")
		case check != "" && recurred[check] && !sure:
			problems = append(problems, fmt.Sprintf("%s names the check \"%s\", which recurred after the previous retro's fix, so it is controversial, with its why", name, check))
		case sure && pyWords(given.Value("why")) == "":
			problems = append(problems, name+" is controversial without a why")
		}
	}
	if !anyWords(lists["went_well"]) {
		problems = append(problems, "`went_well` is empty: record what went well")
	}
	return problems, nil
}

func anyWords(list []any) bool {
	for _, entry := range list {
		if pyWords(entry) != "" {
			return true
		}
	}
	return false
}

func overhaulJudgmentProblems(v any, _ map[string]any) (any, error) {
	lists := map[string][]any{}
	var problems []string
	for _, name := range []string{"verdicts", "findings", "went_well"} {
		value, err := get(v, name)
		if err != nil {
			return nil, err
		}
		list, ok := value.([]any)
		if !ok {
			problems = append(problems, fmt.Sprintf("`%s` is not a list", name))
		}
		lists[name] = list
	}
	if len(problems) > 0 {
		return problems, nil
	}
	block := v.(Object)
	given := block.Value("rules")
	if !truthy(given) {
		given = []any{}
	}
	items, err := iterate(given)
	if err != nil {
		return nil, err
	}
	var rules []string
	for _, r := range items {
		if rule, ok := r.(Object); ok {
			rules = append(rules, str(rule.Value("id")))
		}
	}
	var judged []string
	for i, g := range lists["verdicts"] {
		index := i + 1
		verdict, ok := g.(Object)
		if !ok {
			problems = append(problems, fmt.Sprintf("verdict %d is not an object with %s", index, joinStrings(verdictFields)))
			continue
		}
		rule := pyWords(verdict.Value("rule"))
		name := fmt.Sprintf("verdict %d", index)
		if rule != "" {
			name = "the verdict on " + rule
		}
		if extra := unknownKeys(verdict, verdictFields...); len(extra) > 0 {
			problems = append(problems, fmt.Sprintf("%s has the unknown field %s", name, extra[0]))
		}
		switch {
		case !in(rule, rules) && rule != "":
			problems = append(problems, name+" names no rule of the book")
		case !in(rule, rules):
			problems = append(problems, name+" has no rule")
		case in(rule, judged):
			problems = append(problems, rule+" has two verdicts")
		}
		if !in(rule, judged) {
			judged = append(judged, rule)
		}
		if s, ok := verdict.Value("strays").(string); !ok || !in(s, strays) {
			problems = append(problems, fmt.Sprintf("%s: strays is one of %s", name, joinStrings(strays)))
		}
		if pyWords(verdict.Value("how")) == "" {
			problems = append(problems, name+" has no how")
		}
	}
	for _, rule := range rules {
		if !in(rule, judged) {
			problems = append(problems, rule+" has no verdict")
		}
	}
	if looked, ok := block.Value("looked_at").(Object); !ok {
		problems = append(problems, fmt.Sprintf("`looked_at` is not an object with %s", joinStrings(lookedAt)))
	} else {
		for _, part := range unknownKeys(looked, lookedAt...) {
			problems = append(problems, "`looked_at` has the unknown part "+part)
		}
		for _, part := range lookedAt {
			if pyWords(looked.Value(part)) == "" {
				problems = append(problems, fmt.Sprintf("`looked_at.%s` is empty (\"nothing to change\" is an answer)", part))
			}
		}
	}
	for i, g := range lists["findings"] {
		index := i + 1
		finding, ok := g.(Object)
		if !ok {
			problems = append(problems, fmt.Sprintf("finding %d is not an object with %s", index, joinStrings(overhaulFindingFields)))
			continue
		}
		name, found := findingBasics(finding, index, overhaulFindingFields)
		problems = append(problems, found...)
		rule := pyWords(finding.Value("rule"))
		if rule == "" {
			problems = append(problems, fmt.Sprintf("%s has no rule: a rule's id, or %s", name, newRule))
		} else if rule != newRule && !in(rule, rules) {
			problems = append(problems, fmt.Sprintf("%s names the rule \"%s\", which is not in the book", name, rule))
		}
		if pyWords(finding.Value("place")) == "" {
			problems = append(problems, name+" has no place: the file it changes")
		}
		controversial, held := finding.Get("controversial")
		if !held {
			controversial = false
		}
		if !isBool(controversial) {
			problems = append(problems, name+": controversial is true or false")
		} else if controversial == true && pyWords(finding.Value("why")) == "" {
			problems = append(problems, name+" is controversial without a why")
		}
		sources, held := finding.Get("sources")
		if !held {
			sources = []any{}
		}
		list, isList := sources.([]any)
		good := isList
		for _, item := range list {
			good = good && pyWords(item) != ""
		}
		if !good {
			problems = append(problems, name+": sources is a list of the places cited")
		}
	}
	if !anyWords(lists["went_well"]) {
		problems = append(problems, "`went_well` is empty: record what went well")
	}
	return problems, nil
}
