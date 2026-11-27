package template

import (
	"fmt"
	"math/big"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
)

// A document's recorded inputs (scripts/templates.py "Version"): the effective fields and rules of
// the template it was filled from, as one line under its marker (`<!-- se:inputs <name> <json> -->`)
// or, for a file, in its front matter (`se_inputs_<name>: <json>`). Parse reads a document with
// them, so a template that moves on does not change what an existing document is checked against.
var inputsPattern = regexp.MustCompile(`(?m)^(?:<!-- se:inputs |se_inputs_)([\w-]+)(?: |: )(\{[^\n]*\})(?: -->)?\r?$\n?`)

// inputData is templates.py `input_data` of a template: each attribute that differs from its
// default, without the runtime ones (rule, path, source root, example, code).
func inputData(t *Template) Object {
	o := Object{}
	set := func(key string, value any, skip bool) {
		if !skip {
			o = append(o, Pair{key, value})
		}
	}
	strs := func(list []string) []any {
		out := make([]any, len(list))
		for i, s := range list {
			out[i] = s
		}
		return out
	}
	set("name", t.Name, false)
	set("reader", t.Reader, false)
	set("says", t.Says, false)
	set("actions", strs(t.Actions), false)
	fields := make([]any, len(t.Fields))
	for i, f := range t.Fields {
		fields[i] = fieldData(f)
	}
	set("fields", fields, false)
	rules := t.Rules
	if rules == nil {
		rules = Object{}
	}
	set("rules", rules, false)
	set("order", t.Order, t.Order == 100)
	set("marker", t.Marker, t.Marker == "")
	set("title_pattern", t.TitlePattern, t.TitlePattern == "")
	set("keep_unknown", t.KeepUnknown, t.KeepUnknown)
	set("actors", strs(t.Actors), len(t.Actors) == 0)
	set("scope", t.Scope, len(t.Scope) == 0)
	terms := make([]any, len(t.Terms))
	for i, term := range t.Terms {
		terms[i] = Object{{"term", term.Term}, {"plain", term.Plain}}
	}
	set("terms", terms, len(t.Terms) == 0)
	set("marker_pattern", t.MarkerPattern, t.MarkerPattern == "")
	set("labels", strs(t.Labels), len(t.Labels) == 0)
	set("base", t.Base, t.Base == "")
	set("fallback", t.Fallback, !t.Fallback)
	set("checker", t.Checker, t.Checker == "")
	set("adapter", t.Adapter, len(t.Adapter) == 0)
	set("paths", strs(t.Paths), len(t.Paths) == 0)
	set("repository", t.Repository, t.Repository == "se")
	set("version", t.Version, t.Version == "")
	set("kind", t.Kind, t.Kind == "document")
	set("tags", strs(t.Tags), len(t.Tags) == 0)
	set("digest", t.Digest, t.Digest == "")
	set("message", t.Message, t.Message == "")
	set("manifest", t.Manifest, !t.Manifest)
	return o
}

func fieldData(f *Field) Object {
	o := Object{}
	set := func(key string, value any, skip bool) {
		if !skip {
			o = append(o, Pair{key, value})
		}
	}
	list := func(items []string) []any {
		out := make([]any, len(items))
		for i, s := range items {
			out[i] = s
		}
		return out
	}
	set("name", f.Name, false)
	set("kind", f.Kind, false)
	set("heading", f.Heading, f.Heading == "")
	set("required", f.Required, !f.Required)
	set("none_ok", f.NoneOK, !f.NoneOK)
	set("says", f.Says, f.Says == "")
	set("exact_heading", f.ExactHeading, !f.ExactHeading)
	set("verbatim", f.Verbatim, !f.Verbatim)
	set("source", f.Source, f.Source == "")
	set("label", f.Label, f.Label == "")
	set("choices", list(f.Choices), len(f.Choices) == 0)
	set("numbered", f.Numbered, !f.Numbered)
	set("continue_numbers", f.ContinueNumbers, !f.ContinueNumbers)
	set("markers", f.Markers, !f.Markers)
	set("lang", f.Lang, f.Lang == "sh")
	set("max_words", f.MaxWords, f.MaxWords == 0)
	set("first_sentence_chars", f.FirstSentenceChars, f.FirstSentenceChars == 0)
	set("actor", f.Actor, !f.Actor)
	set("one_sentence", f.OneSentence, !f.OneSentence)
	set("not_picked", f.NotPicked, !f.NotPicked)
	set("shape", f.Shape, f.Shape == "")
	set("quote", f.Quote, !f.Quote)
	set("checkable", f.Checkable, !f.Checkable)
	set("node", f.Node, f.Node == "")
	set("pin", f.Pin, f.Pin == "")
	set("since", f.Since, f.Since == "")
	set("carried", list(f.Carried), len(f.Carried) == 0)
	set("fence", f.Fence, f.Fence == "")
	set("row", f.Row, f.Row == "")
	cases := make([]any, len(f.Cases))
	for i, pair := range f.Cases {
		cases[i] = []any{pair.Key, pair.Value}
	}
	set("cases", cases, len(f.Cases) == 0)
	if f.nested != nil {
		set("nested", inputData(f.nested), false)
	}
	return o
}

// inputPayload is templates.py `input_payload`: Python's json.dumps of the input data with sorted
// keys, ASCII only and no spaces, `<` and `>` escaped so the line stays one HTML comment.
func inputPayload(t *Template) string {
	var b strings.Builder
	dumpJSON(&b, inputData(t))
	return strings.NewReplacer("<", "\\u003c", ">", "\\u003e").Replace(b.String())
}

// inputLine is the line a document records its inputs in.
func inputLine(t *Template) string {
	if t.writesFile() {
		return "se_inputs_" + t.Name + ": " + inputPayload(t)
	}
	return "<!-- se:inputs " + t.Name + " " + inputPayload(t) + " -->"
}

// recordInputs is templates.py `record_inputs`: body with the inputs line under the marker naming
// the template, where the body records none yet.
func recordInputs(t *Template, body string) string {
	if t.IsAdapter() || t.Message != "" || t.writesFile() {
		return body
	}
	switch t.Kind {
	case "block", "entry", "interface", "code":
		return body
	}
	for _, m := range inputsPattern.FindAllStringSubmatch(body, -1) {
		if m[1] == t.Name {
			return body
		}
	}
	marker := markerOf(t, body)
	if marker == "" {
		return body
	}
	return strings.Replace(body, marker+"\n", marker+"\n"+inputLine(t)+"\n", 1)
}

// markerOf is the line of body that names the template: its template marker, else its own marker.
func markerOf(t *Template, body string) string {
	for _, m := range templateMarkerLine.FindAllStringSubmatch(body, -1) {
		if m[1] == t.Name {
			return strip(m[0])
		}
	}
	if t.Marker != "" && strings.Contains(body, t.Marker) {
		return t.Marker
	}
	return ""
}

// inputsFor is templates.py `inputs_for`: the template a body is read with, its recorded inputs
// where they hold the version it records. The Go engine reads no template history, so a recorded
// version without inputs reads against the template.
func inputsFor(t *Template, body string) (*Template, error) {
	recorded := markedVersion(t, body)
	if recorded == "" {
		recorded = frontVersion(t, body)
	}
	for _, m := range inputsPattern.FindAllStringSubmatch(body, -1) {
		if m[1] != t.Name {
			continue
		}
		data, err := pyJSON(m[2])
		var frozen *Template
		if err == nil {
			frozen, err = inputTemplate(data)
		}
		if err != nil {
			return nil, fail("templates: %s's recorded inputs are unreadable: %v; restore its input record", t.Name, err)
		}
		if recorded == "" || recorded == frozen.Version {
			return frozen, nil
		}
		if recorded == t.Version {
			return t, nil
		}
		return nil, fail("templates: %s records %s, but its saved inputs are %s; restore that version or run `templates.py renew %s --body-file <file>`", t.Name, recorded, frozen.Version, t.Name)
	}
	return t, nil
}

// inputTemplate is templates.py `input_template`: the template recorded input data describes.
func inputTemplate(data any) (*Template, error) {
	o, ok := data.(Object)
	if !ok {
		return nil, fmt.Errorf("the inputs are no object")
	}
	t := &Template{Order: 100, KeepUnknown: true, Repository: "se", Kind: "document", Rules: Object{}}
	for _, pair := range o {
		v := pair.Value
		switch pair.Key {
		case "name":
			t.Name = str(v)
		case "reader":
			t.Reader = str(v)
		case "says":
			t.Says = str(v)
		case "actions":
			t.Actions = strings_(v)
		case "rules":
			t.Rules, _ = v.(Object)
		case "order":
			t.Order = toInt(v)
		case "marker":
			t.Marker = str(v)
		case "title_pattern":
			t.TitlePattern = str(v)
		case "keep_unknown":
			t.KeepUnknown = truthy(v)
		case "actors":
			t.Actors = strings_(v)
		case "scope":
			t.Scope, _ = v.(Object)
		case "terms":
			list, _ := v.([]any)
			for _, item := range list {
				term, _ := item.(Object)
				t.Terms = append(t.Terms, Term{str(term.Value("term")), str(term.Value("plain"))})
			}
		case "marker_pattern":
			t.MarkerPattern = str(v)
		case "labels":
			t.Labels = strings_(v)
		case "base":
			t.Base = str(v)
		case "fallback":
			t.Fallback = truthy(v)
		case "checker":
			t.Checker = str(v)
		case "adapter":
			t.Adapter, _ = v.(Object)
		case "paths":
			t.Paths = strings_(v)
		case "repository":
			t.Repository = str(v)
		case "version":
			t.Version = str(v)
		case "kind":
			t.Kind = str(v)
		case "tags":
			t.Tags = strings_(v)
		case "digest":
			t.Digest = str(v)
		case "message":
			t.Message = str(v)
		case "manifest":
			t.Manifest = truthy(v)
		case "fields":
		default:
			return nil, fmt.Errorf("'%s' is no template attribute", pair.Key)
		}
	}
	list, _ := o.Value("fields").([]any)
	for _, item := range list {
		f, err := inputField(item)
		if err != nil {
			return nil, err
		}
		t.Fields = append(t.Fields, f)
	}
	return t, nil
}

func inputField(data any) (*Field, error) {
	o, ok := data.(Object)
	if !ok {
		return nil, fmt.Errorf("a field is no object")
	}
	f := &Field{Lang: "sh"}
	for _, pair := range o {
		v := pair.Value
		switch pair.Key {
		case "name":
			f.Name = str(v)
		case "kind":
			f.Kind = str(v)
		case "heading":
			f.Heading = str(v)
		case "required":
			f.Required = truthy(v)
		case "none_ok":
			f.NoneOK = truthy(v)
		case "says":
			f.Says = str(v)
		case "exact_heading":
			f.ExactHeading = truthy(v)
		case "verbatim":
			f.Verbatim = truthy(v)
		case "source":
			f.Source = str(v)
		case "label":
			f.Label = str(v)
		case "choices":
			f.Choices = strings_(v)
		case "numbered":
			f.Numbered = truthy(v)
		case "continue_numbers":
			f.ContinueNumbers = truthy(v)
		case "markers":
			f.Markers = truthy(v)
		case "lang":
			f.Lang = str(v)
		case "max_words":
			f.MaxWords = toInt(v)
		case "first_sentence_chars":
			f.FirstSentenceChars = toInt(v)
		case "actor":
			f.Actor = truthy(v)
		case "one_sentence":
			f.OneSentence = truthy(v)
		case "not_picked":
			f.NotPicked = truthy(v)
		case "shape":
			f.Shape = str(v)
		case "quote":
			f.Quote = truthy(v)
		case "checkable":
			f.Checkable = truthy(v)
		case "node":
			f.Node = str(v)
		case "pin":
			f.Pin = str(v)
		case "since":
			f.Since = str(v)
		case "carried":
			f.Carried = strings_(v)
		case "fence":
			f.Fence = str(v)
		case "row":
			f.Row = str(v)
		case "cases":
			list, _ := v.([]any)
			for _, item := range list {
				pair, _ := item.([]any)
				if len(pair) == 2 {
					f.Cases = append(f.Cases, Pair{str(pair[0]), pair[1]})
				}
			}
		case "nested":
			nested, err := inputTemplate(v)
			if err != nil {
				return nil, err
			}
			f.nested = nested
		default:
			return nil, fmt.Errorf("'%s' is no field attribute", pair.Key)
		}
	}
	if reference.MatchString(f.Shape) {
		rule, ok := References[f.Shape]
		if !ok {
			return nil, fmt.Errorf("%s does not resolve (the Go engine holds no %s)", f.Shape, f.Shape)
		}
		f.rule = rule
	}
	return f, nil
}

func strings_(v any) []string {
	list, _ := v.([]any)
	var out []string
	for _, item := range list {
		out = append(out, str(item))
	}
	return out
}

func toInt(v any) int {
	switch x := v.(type) {
	case int:
		return x
	case int64:
		return int(x)
	case *big.Int:
		return int(x.Int64())
	case float64:
		return int(x)
	}
	return 0
}

// dumpJSON writes v as Python's json.dumps(v, ensure_ascii=True, separators=(",", ":"),
// sort_keys=True) does.
func dumpJSON(b *strings.Builder, v any) {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		dumpString(b, x)
	case int:
		b.WriteString(strconv.Itoa(x))
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case *big.Int:
		b.WriteString(x.String())
	case float64:
		switch text := pyFloat(x); text {
		case "nan":
			b.WriteString("NaN")
		case "inf":
			b.WriteString("Infinity")
		case "-inf":
			b.WriteString("-Infinity")
		default:
			b.WriteString(text)
		}
	case []any:
		b.WriteByte('[')
		for i, item := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			dumpJSON(b, item)
		}
		b.WriteByte(']')
	case []string:
		items := make([]any, len(x))
		for i, s := range x {
			items[i] = s
		}
		dumpJSON(b, items)
	case Object:
		pairs := append(Object{}, x...)
		sort.SliceStable(pairs, func(i, j int) bool { return pairs[i].Key < pairs[j].Key })
		b.WriteByte('{')
		for i, pair := range pairs {
			if i > 0 {
				b.WriteByte(',')
			}
			dumpString(b, pair.Key)
			b.WriteByte(':')
			dumpJSON(b, pair.Value)
		}
		b.WriteByte('}')
	default:
		dumpString(b, str(v))
	}
}

func dumpString(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			switch {
			case r >= ' ' && r <= '~':
				b.WriteRune(r)
			case r > 0xffff:
				hi, lo := utf16.EncodeRune(r)
				fmt.Fprintf(b, `\u%04x\u%04x`, hi, lo)
			default:
				fmt.Fprintf(b, `\u%04x`, r)
			}
		}
	}
	b.WriteByte('"')
}
