package template

import (
	"fmt"
	"reflect"
	"sort"
	"strings"
)

// Overlays (docs/templates.md "Template repositories"): `templates/<name>.overlay.md`, beside the
// template note it extends, adds to it or tightens it, never loosens it; the port of templates.py's
// `overlay_data`, `_overlaid` and `_tightens`, which `_loaded` applies per layer.

const overlaySuffix = ".overlay.md"

var (
	overlayKeys   = []string{"extends", "says", "tags", "rules", "fields", "example"}
	strictness    = map[string]int{Off: 0, Warn: 1, Refuse: 2}
	tighterOn     = []string{"required", "exact_heading", "actor", "one_sentence", "not_picked", "quote"}
	tighterOff    = []string{"none_ok"}
	tighterLimits = []string{"max_words", "first_sentence_chars"}
)

// says is templates.py `_says`: instructions joined in turn, the template's first.
func says(parts ...any) string {
	var kept []string
	for _, part := range parts {
		if !truthy(part) || strip(str(part)) == "" {
			continue
		}
		kept = append(kept, strip(str(part)))
	}
	return strings.Join(kept, " ")
}

// templateChain is templates.py `_chain`: the name, then each template it extends, as raw holds them.
func templateChain(name string, raw map[string]Object) []string {
	var chain []string
	for {
		data, ok := raw[name]
		if !ok || in(name, chain) {
			return chain
		}
		chain = append(chain, name)
		name, _ = data.Value("extends").(string)
	}
}

// inherited is templates.py `_inherited`: the entry of a field the template has, its own or
// inherited, a copy; nil where none does.
func inherited(name, field string, raw map[string]Object) Object {
	for _, template := range templateChain(name, raw) {
		list, _ := raw[template].Value("fields").([]any)
		for _, item := range list {
			if entry, ok := item.(Object); ok && entry.Value("name") == field {
				return entry.Copy()
			}
		}
		if in(field, stringsOf(raw[template].Value("remove"))) {
			return nil
		}
	}
	return nil
}

func inheritedKey(name, key string, raw map[string]Object) any {
	for _, template := range templateChain(name, raw) {
		if v, ok := raw[template].Get(key); ok {
			return v
		}
	}
	return nil
}

// overlaid is templates.py `_overlaid`: raw with each overlaid template's data merged with its
// overlay, a template's before those that extend it.
func overlaid(raw map[string]Object, overlays map[string][2]string) (map[string]Object, error) {
	merged := map[string]Object{}
	for name, data := range raw {
		merged[name] = data
	}
	names := sortedKeys(overlays)
	sort.SliceStable(names, func(i, j int) bool {
		return len(templateChain(names[i], raw)) < len(templateChain(names[j], raw))
	})
	for _, name := range names {
		data, err := overlayData(name, merged, overlays[name][0], overlays[name][1])
		if err != nil {
			return nil, err
		}
		merged[name] = data
	}
	return merged, nil
}

func fieldIndex(own []Object, name string) int {
	for i, item := range own {
		if item.Value("name") == name {
			return i
		}
	}
	return -1
}

// overlayData is templates.py `overlay_data`: the template's data with its overlay merged in.
func overlayData(name string, raw map[string]Object, text, where string) (Object, error) {
	data, body, first, err := noteParts(text, where)
	if err != nil {
		return nil, err
	}
	var unknown []string
	for _, pair := range data {
		if !in(pair.Key, overlayKeys) && !in(pair.Key, unknown) {
			unknown = append(unknown, pair.Key)
		}
	}
	if len(unknown) > 0 {
		sort.Strings(unknown)
		verb := "are"
		if len(unknown) == 1 {
			verb = "is"
		}
		return nil, fail("%s: an overlay only adds or tightens; %s %s the template's to say. An overlay's keys are %s", where, joinStrings(unknown), verb, joinStrings(overlayKeys))
	}
	if v, _ := data.Get("extends"); v != name {
		return nil, fail("%s: extends is %s; an overlay extends its template, `extends: %s`", where, repr(v), name)
	}
	base := raw[name]
	merged := base.Copy()
	isInterface := base.Value("kind") == interfaceKind
	if v, ok := data.Get("says"); ok {
		merged.Set("says", says(inheritedKey(name, "says", raw), v))
	}
	tags, has := data.Get("tags")
	if !has {
		tags = []any{}
	}
	added, ok := tags.([]any)
	if !ok {
		return nil, fail(`%s: tags is a list of words the overlay adds, such as ["meeting"]`, where)
	}
	var allTags []any
	for _, tag := range append(append([]any{}, listOf(base.Value("tags"))...), added...) {
		seen := false
		for _, have := range allTags {
			seen = seen || equal(have, tag)
		}
		if !seen {
			allTags = append(allTags, tag)
		}
	}
	if allTags == nil {
		allTags = []any{}
	}
	merged.Set("tags", allTags)
	rules, has := data.Get("rules")
	if !has {
		rules = Object{}
	}
	given, ok := rules.(Object)
	if !ok {
		return nil, fail(`%s: rules maps each rule to refuse, warn or "off"`, where)
	}
	baseRules, _ := base.Value("rules").(Object)
	allRules := baseRules.Copy()
	if allRules == nil {
		allRules = Object{}
	}
	for _, pair := range given {
		allRules.Set(pair.Key, pair.Value)
	}
	merged.Set("rules", allRules)
	if v, ok := data.Get("example"); ok {
		given, isObject := v.(Object)
		if !isObject {
			return nil, fail("%s: example is a mapping, its title and its fields", where)
		}
		example, _ := base.Value("example").(Object)
		made := example.Copy()
		if made == nil {
			made = Object{}
		}
		for _, pair := range given {
			made.Set(pair.Key, pair.Value)
		}
		baseFields, _ := example.Value("fields").(Object)
		fields := baseFields.Copy()
		if fields == nil {
			fields = Object{}
		}
		givenFields, _ := given.Value("fields").(Object)
		for _, pair := range givenFields {
			fields.Set(pair.Key, pair.Value)
		}
		made.Set("fields", fields)
		merged.Set("example", made)
	}
	var own []Object
	for _, item := range listOf(base.Value("fields")) {
		if entry, ok := item.(Object); ok {
			own = append(own, entry.Copy())
		}
	}
	var addedFields []string
	entriesValue, has := data.Get("fields")
	if !has {
		entriesValue = []any{}
	}
	entries, ok := entriesValue.([]any)
	for _, e := range entries {
		entry, isObject := e.(Object)
		ok = ok && isObject && truthy(entry.Value("name"))
	}
	if !ok {
		return nil, fail("%s: fields is a list of mappings, each naming its field", where)
	}
	for _, e := range entries {
		entry := e.(Object)
		fieldName := str(entry.Value("name"))
		found := inherited(name, fieldName, raw)
		of := func(key string) any {
			if v, ok := entry.Get(key); ok {
				return v
			}
			return found.Value(key)
		}
		sectioned := !isInterface && !truthy(of("source")) && !truthy(of("label")) && !truthy(of("fence"))
		for _, key := range []string{"heading", "says"} {
			if entry.Has(key) && sectioned {
				return nil, fail("%s: field %s has its section in the overlay's body, which owns its %s; take %s out of the front matter", where, fieldName, key, key)
			}
		}
		made := found.Copy()
		if made == nil {
			made = Object{}
		}
		for _, pair := range entry {
			made.Set(pair.Key, pair.Value)
		}
		if found != nil && entry.Has("says") {
			made.Set("says", says(found.Value("says"), entry.Value("says")))
		}
		if found == nil {
			addedFields = append(addedFields, fieldName)
		}
		if i := fieldIndex(own, fieldName); i < 0 {
			own = append(own, made)
		} else {
			own[i] = made
		}
	}
	level := 2
	if scope, ok := base.Value("scope").(Object); ok && len(scope) > 0 {
		if v, ok := scope.Value("level").(int); ok {
			level = v
		}
	}
	var sections [][3]string
	if isInterface {
		if _, err := interfaceData(Object{}, nil, body, where, first); err != nil {
			return nil, err
		}
	} else if sections, err = skeleton(body, where, first, level); err != nil {
		return nil, err
	}
	var seen []string
	for _, section := range sections {
		fieldName, heading, instruction := section[0], section[1], section[2]
		if in(fieldName, seen) {
			return nil, fail("%s: two sections add to field %s; give it one", where, fieldName)
		}
		seen = append(seen, fieldName)
		index := fieldIndex(own, fieldName)
		var entry Object
		if index >= 0 {
			entry = own[index]
		} else {
			entry = inherited(name, fieldName, raw)
		}
		if entry == nil {
			return nil, fail("%s: section %s adds to field %s, which neither %s nor the overlay's fields hold; name it in the overlay's fields", where, heading, fieldName, name)
		}
		if in(fieldName, addedFields) {
			entry.Set("heading", heading)
			entry.Set("says", instruction)
		} else {
			if norm(heading) != norm(str(orEmpty(entry.Value("heading"), entry.Has("heading")))) {
				return nil, fail("%s: section %s adds to field %s, whose heading is %s; an overlay adds under the template's heading, never renames it", where, heading, fieldName, repr(entry.Value("heading")))
			}
			entry = entry.Copy()
			entry.Set("says", says(orEmpty(entry.Value("says"), entry.Has("says")), instruction))
		}
		if index < 0 {
			own = append(own, entry)
		} else {
			own[index] = entry
		}
	}
	for _, fieldName := range addedFields {
		entry := own[fieldIndex(own, fieldName)]
		if !isInterface && !truthy(entry.Value("source")) && !truthy(entry.Value("label")) && !truthy(entry.Value("fence")) && !in(fieldName, seen) {
			return nil, fail("%s: field %s is added without its section; give it one in the overlay's body, its heading and `<!-- %s: <instruction> -->`", where, fieldName, fieldName)
		}
	}
	fields := make([]any, len(own))
	for i, entry := range own {
		fields[i] = entry
	}
	merged.Set("fields", fields)
	if order, ok := base.Get("order"); ok && len(addedFields) > 0 {
		merged.Set("order", append(append([]any{}, listOf(order)...), toAny(addedFields)...))
	}
	return merged, nil
}

// orEmpty is Python's entry.get(key, ""): the value where the key is held, else "".
func orEmpty(v any, held bool) any {
	if !held {
		return ""
	}
	return v
}

// tightens is templates.py `_tightens`: refuse an overlay whose template loosens the template's.
func tightens(base, over *Template, where string) error {
	var problems []string
	same := []struct {
		key        string
		was, would any
	}{
		{"name", base.Name, over.Name}, {"version", base.Version, over.Version}, {"kind", base.Kind, over.Kind},
		{"reader", base.Reader, over.Reader}, {"actions", base.Actions, over.Actions}, {"order", base.Order, over.Order},
		{"marker", base.Marker, over.Marker}, {"title_pattern", base.TitlePattern, over.TitlePattern},
		{"keep_unknown", base.KeepUnknown, over.KeepUnknown}, {"actors", base.Actors, over.Actors},
		{"scope", base.Scope, over.Scope}, {"paths", base.Paths, over.Paths}, {"marker_pattern", base.MarkerPattern, over.MarkerPattern},
		{"labels", base.Labels, over.Labels}, {"base", base.Base, over.Base}, {"fallback", base.Fallback, over.Fallback},
		{"checker", base.Checker, over.Checker}, {"adapter", base.Adapter, over.Adapter}, {"message", base.Message, over.Message},
		{"is_adapter", base.IsAdapter(), over.IsAdapter()}, {"manifest", base.Manifest, over.Manifest},
	}
	for _, key := range same {
		if !reflect.DeepEqual(key.was, key.would) {
			problems = append(problems, "it changes "+key.key)
		}
	}
	if !strings.HasPrefix(over.Says, base.Says) {
		problems = append(problems, "it rewrites the template's says; add to it")
	}
	for _, tag := range base.Tags {
		if !in(tag, over.Tags) {
			problems = append(problems, "it takes tag "+tag+" away")
		}
	}
	rules := base.Rules.Keys()
	sort.Strings(rules)
	for _, rule := range rules {
		severity, now := str(base.Rules.Value(rule)), over.Severity(rule)
		if strictness[now] < strictness[severity] {
			problems = append(problems, fmt.Sprintf("it loosens rule %s from %s to %s", rule, severity, now))
		}
	}
	var names, kept, order []string
	for _, item := range over.Fields {
		names = append(names, item.Name)
	}
	for _, item := range base.Fields {
		if in(item.Name, names) {
			kept = append(kept, item.Name)
		} else {
			problems = append(problems, "it takes field "+item.Name+" away")
		}
	}
	for _, name := range names {
		if in(name, kept) {
			order = append(order, name)
		}
	}
	if strings.Join(kept, "\x00") != strings.Join(order, "\x00") {
		problems = append(problems, "it reorders the template's fields")
	}
	for _, item := range base.Fields {
		if other := over.Field(item.Name); other != nil {
			for _, problem := range fieldTightens(item, other) {
				problems = append(problems, "field "+item.Name+": "+problem)
			}
		}
	}
	if len(problems) > 0 {
		return fail(`%s: the overlay loosens %s: %s. An overlay only adds or tightens: it adds instructions, fields, tags and rules and makes a rule stricter (docs/templates.md "Template repositories")`, where, base.Name, strings.Join(problems, "; "))
	}
	return nil
}

// fieldTightens is templates.py `_field_tightens`: what the overlay's field loosens or changes of
// the template's, key by key in the order Python's Field declares them.
func fieldTightens(base, other *Field) []string {
	keys := []struct {
		key        string
		was, would any
	}{
		{"name", base.Name, other.Name}, {"kind", base.Kind, other.Kind}, {"heading", base.Heading, other.Heading},
		{"required", base.Required, other.Required}, {"none_ok", base.NoneOK, other.NoneOK}, {"says", base.Says, other.Says},
		{"exact_heading", base.ExactHeading, other.ExactHeading}, {"verbatim", base.Verbatim, other.Verbatim},
		{"source", base.Source, other.Source}, {"label", base.Label, other.Label}, {"choices", base.Choices, other.Choices},
		{"numbered", base.Numbered, other.Numbered}, {"continue_numbers", base.ContinueNumbers, other.ContinueNumbers},
		{"markers", base.Markers, other.Markers}, {"lang", base.Lang, other.Lang}, {"max_words", base.MaxWords, other.MaxWords},
		{"first_sentence_chars", base.FirstSentenceChars, other.FirstSentenceChars}, {"actor", base.Actor, other.Actor},
		{"one_sentence", base.OneSentence, other.OneSentence}, {"not_picked", base.NotPicked, other.NotPicked},
		{"shape", base.Shape, other.Shape}, {"quote", base.Quote, other.Quote}, {"node", base.Node, other.Node},
		{"pin", base.Pin, other.Pin}, {"fence", base.Fence, other.Fence},
	}
	var problems []string
	for _, k := range keys {
		if k.key == "choices" {
			was, now := base.Choices, other.Choices
			if strings.Join(was, "\x00") == strings.Join(now, "\x00") && len(was) == len(now) {
				continue
			}
			subset := len(now) > 0
			for _, choice := range now {
				subset = subset && in(choice, was)
			}
			if !subset {
				problems = append(problems, fmt.Sprintf("choices widen from %s to %s", joinStrings(was), joinStrings(now)))
			}
			continue
		}
		if reflect.DeepEqual(k.was, k.would) {
			continue
		}
		switch {
		case k.key == "says":
			if !strings.HasPrefix(other.Says, base.Says) {
				problems = append(problems, "its says is rewritten; add to it")
			}
		case in(k.key, tighterOn):
			if k.was.(bool) {
				problems = append(problems, k.key+" is turned off")
			}
		case in(k.key, tighterOff):
			if !k.was.(bool) {
				problems = append(problems, k.key+" is turned on")
			}
		case in(k.key, tighterLimits):
			was, now := k.was.(int), k.would.(int)
			if now == 0 || (was != 0 && now > was) {
				problems = append(problems, fmt.Sprintf("%s is raised from %s to %s", k.key, limitText(was), limitText(now)))
			}
		default:
			problems = append(problems, fmt.Sprintf("%s changes from %s to %s", k.key, repr(k.was), repr(k.would)))
		}
	}
	return problems
}

func limitText(n int) string {
	if n == 0 {
		return "none"
	}
	return fmt.Sprint(n)
}
