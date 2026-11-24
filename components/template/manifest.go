package template

import (
	"fmt"
	"sort"
	"strings"
)

// Template manifests (scripts/templates.py "Template manifests"): templates/<name>/manifest.md and
// its template nodes beside it, obs's note types, read as the data a note gives (noteData), so
// every reader after the load is the one for both forms.

// manifestData is templates.py `manifest_data`: the manifest <name>/manifest.md of files, with its
// nodes, as the data build reads, and the text its digest covers: the manifest's, then each
// template node's in its order, a NUL byte between.
func manifestData(name string, files map[string]string, whereOf func(string) string) (Object, string, error) {
	key := name + "/" + manifestFile
	where := whereOf(key)
	front, body, first, err := noteParts(files[key], where)
	if err != nil {
		return nil, "", err
	}
	var declared Object
	if obs, ok := front.Value("obs").(Object); ok {
		declared, _ = obs.Value("template").(Object)
	}
	if declared == nil {
		return nil, "", fail("%s: a template manifest carries obs.template, its name and version, in its front matter", where)
	}
	var unknown []string
	for _, k := range declared.Keys() {
		if k != "name" && k != "version" && k != "source" {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, "", fail("%s: obs.template has unknown keys %s; its keys are name, version and source", where, joinStrings(unknown))
	}
	for _, part := range []string{"name", "version", "source"} {
		if v, ok := declared.Get(part); ok {
			if s, isString := v.(string); !isString || strip(s) == "" {
				return nil, "", fail("%s: obs.template.%s is %s; write it as nonempty text", where, part, repr(v))
			}
		}
	}
	if s, _ := declared.Value("name").(string); s != name {
		return nil, "", fail("%s: obs.template.name is %s; it is the manifest's folder's name, %s", where, repr(declared.Value("name")), repr(name))
	}
	version, isString := declared.Value("version").(string)
	if !isString || !manifestVersion.MatchString(version) {
		return nil, "", fail("%s: obs.template.version is %s; write one to three whole numbers joined by dots, such as \"2\" or \"1.2.0\"", where, repr(declared.Value("version")))
	}
	type chapter struct {
		number        int
		target, alias string
	}
	var chapters []chapter
	var prose []any
	for i, line := range splitLines(body, false) {
		if m := tocLine.FindStringSubmatch(line); m != nil {
			chapters = append(chapters, chapter{first + i, strip(m[1]), strip(m[2])})
		} else if strip(line) != "" {
			prose = append(prose, strip(line))
		}
	}
	fields := []any{}
	texts := []string{files[key]}
	for _, c := range chapters {
		node := name + "/" + c.target + templateSuffix
		text, listed := files[node]
		if strings.Contains(c.target, "/") || !listed {
			return nil, "", fail("%s:%d: chapter [[%s]] is no note beside the manifest, %s/%s", where, c.number, c.target, TemplatesFolder, node)
		}
		entry, err := templateNode(text, whereOf(node), c.target, c.alias)
		if err != nil {
			return nil, "", err
		}
		if entry == nil {
			continue // an ordinary chapter, such as a note on how to use the template
		}
		for _, made := range fields {
			if made.(Object).Value("name") == entry.Value("name") {
				return nil, "", fail("%s:%d: chapter [[%s]] is listed twice", where, c.number, c.target)
			}
		}
		fields = append(fields, entry)
		texts = append(texts, text)
	}
	if len(fields) == 0 {
		return nil, "", fail("%s: a template manifest lists at least one template node, a chapter whose front matter carries obs.guidance", where)
	}
	said := says(prose...)
	if said == "" {
		if title, ok := front.Value("title").(string); ok {
			said = title
		}
	}
	if said == "" {
		said = name
	}
	return Object{{"name", name}, {"version", version}, {"kind", "document"}, {"tags", []any{}},
		{"reader", "owner"}, {"says", said}, {"rules", Object{{"required", Refuse}}}, {"fields", fields},
		{"manifest", true}}, strings.Join(texts, "\x00"), nil
}

// templateNode is templates.py `_template_node`: a template node as the entry of its field, nil
// for an ordinary chapter, a note without obs.guidance.
func templateNode(text, where, target, alias string) (Object, error) {
	if !strings.HasPrefix(strings.ReplaceAll(text, "\r\n", "\n"), "---\n") {
		return nil, nil
	}
	front, body, _, err := noteParts(text, where)
	if err != nil {
		return nil, err
	}
	obs, _ := front.Value("obs").(Object)
	guidanceValue, has := obs.Get("guidance")
	if obs == nil || !has || guidanceValue == nil {
		return nil, nil
	}
	guidance, ok := guidanceValue.(Object)
	if !ok {
		return nil, fail("%s: obs.guidance is a mapping of %s", where, joinStrings(guidanceKeys))
	}
	var unknown []string
	for _, k := range guidance.Keys() {
		if !in(k, guidanceKeys) {
			unknown = append(unknown, k)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		return nil, fail("%s: obs.guidance has unknown keys %s; its keys are %s", where, joinStrings(unknown), joinStrings(guidanceKeys))
	}
	for _, part := range guidanceKeys {
		v, given := guidance.Get(part)
		if (part == "contents" || part == "gate") && !given {
			return nil, fail("%s: obs.guidance.%s is required", where, part)
		}
		if s, isString := v.(string); given && (!isString || strip(s) == "") {
			return nil, fail("%s: obs.guidance.%s is %s; write it as nonempty text", where, part, repr(v))
		}
	}
	gate := guidance.Value("gate").(string)
	if !in(gate, gates) {
		return nil, fail("%s: obs.guidance.gate is %s; one of %s", where, repr(gate), joinStrings(gates))
	}
	if strip(body) != slot {
		return nil, fail("%s: a template node's body is its fill slot alone, a paragraph of %s", where, slot)
	}
	field := nodeNameSpaces.ReplaceAllString(casefold(strip(target)), "_")
	if !nodeFieldName.MatchString(field) {
		return nil, fail("%s: the note's name %s makes no field name; name it in lower-case letters, digits and hyphens", where, repr(target))
	}
	parts := []any{guidance.Value("contents")}
	for _, part := range []string{"motivation", "form", "sources"} {
		if v, ok := guidance.Get(part); ok {
			parts = append(parts, fmt.Sprintf("%s: %s", guidanceLabels[part], v.(string)))
		}
	}
	heading := alias
	if heading == "" {
		heading = target
	}
	return Object{{"name", field}, {"kind", "text"}, {"required", gate == "mandatory"},
		{"heading", heading}, {"says", says(parts...)}}, nil
}
