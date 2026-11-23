package template

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
)

// Filled is a filled template: the one value a templated target accepts (SE#1683, the person's
// decision of 22 Nov, typed templates). Parse, don't validate: Fill checks the fields once, against
// the template and the raw input, and only a fill that nothing refuses becomes a Filled. A target
// then relies on its type and checks nothing again.
//
// No other code can construct one. Its fields are unexported, so another package holds only the
// zero value, which every target refuses, or a Filled that Fill made. Across the bus, as JSON, it
// carries a seal: an HMAC of its content under a key this process drew at start, which
// UnmarshalJSON verifies, so JSON written by hand, or a Filled whose content was changed, does not
// decode as one.
type Filled struct {
	content filledContent
	seal    string
}

type filledContent struct {
	Template   string    `json:"template"`
	Repository string    `json:"repository"`
	Version    string    `json:"version"`
	Digest     string    `json:"digest"`
	Title      *string   `json:"title"`
	Fields     Object    `json:"fields"`
	Document   string    `json:"document"`
	Warnings   []Finding `json:"warnings"`
}

// The key a Filled's seal is made with: drawn once per process, never written anywhere.
var sealKey = func() []byte {
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		panic(fmt.Sprintf("template: no random key for the filled template's seal: %v", err))
	}
	return key
}()

// sealOf is the HMAC of the content's canonical JSON, its keys sorted, so the seal holds however a
// bus between components orders a mapping's keys.
func sealOf(c filledContent) string {
	data, err := json.Marshal(c)
	if err != nil {
		return ""
	}
	var generic any
	if err := json.Unmarshal(data, &generic); err != nil {
		return ""
	}
	if data, err = json.Marshal(generic); err != nil {
		return ""
	}
	mac := hmac.New(sha256.New, sealKey)
	mac.Write(data)
	return hex.EncodeToString(mac.Sum(nil))
}

// Template is the name of the template the value fills.
func (f Filled) Template() string { return f.content.Template }

// Repository is the repository the template resolved from: se, project or a template repository.
func (f Filled) Repository() string { return f.content.Repository }

// Version is the template's version the value was filled at.
func (f Filled) Version() string { return f.content.Version }

// Digest is the template's digest, its marker's last word.
func (f Filled) Digest() string { return f.content.Digest }

// Title is the title the fill took, "" and false where it took none.
func (f Filled) Title() (string, bool) {
	if f.content.Title == nil {
		return "", false
	}
	return *f.content.Title, true
}

// Fields are the field values the fill checked, a copy.
func (f Filled) Fields() Object { return f.content.Fields.Copy() }

// Document is the text the fill rendered: what a target writes, files or sends.
func (f Filled) Document() string { return f.content.Document }

// Warnings are the findings of the fill that warn and never refuse.
func (f Filled) Warnings() []Finding { return append([]Finding{}, f.content.Warnings...) }

// Valid reports whether the value is one Fill made: the zero value, and any value whose seal does
// not hold, is none.
func (f Filled) Valid() bool {
	return f.seal != "" && f.content.Template != "" && hmac.Equal([]byte(f.seal), []byte(sealOf(f.content)))
}

type filledJSON struct {
	filledContent
	Seal string `json:"seal"`
}

// MarshalJSON writes the value with its seal, as it rides the bus to another component.
func (f Filled) MarshalJSON() ([]byte, error) {
	return json.Marshal(filledJSON{f.content, f.seal})
}

// UnmarshalJSON reads a value another component passed on, refusing one whose seal this process did
// not make: free JSON of the same shape is no filled template.
func (f *Filled) UnmarshalJSON(data []byte) error {
	var v filledJSON
	if err := json.Unmarshal(data, &v); err != nil {
		return fmt.Errorf("a filled template is the template component's answer to fill: %w", err)
	}
	made := Filled{v.filledContent, v.Seal}
	if !made.Valid() {
		return &Error{fmt.Sprintf("this is no filled template of %s: only the template component's fill makes one, and its seal does not hold; fill the template, not a text of its shape", orUnnamed(v.Template))}
	}
	*f = made
	return nil
}

func orUnnamed(name string) string {
	if name == "" {
		return "any template"
	}
	return name
}

// Refusal is a fill that something refuses: every finding, and nothing made.
type Refusal struct {
	Template string
	Findings []Finding
}

func (r *Refusal) Error() string {
	var lines []string
	for _, f := range r.Findings {
		if f.Severity == Refuse {
			lines = append(lines, f.String())
		}
	}
	return fmt.Sprintf("templates fill %s: refused, nothing was made; fix every finding and fill again:\n%s", r.Template, strings.Join(lines, "\n"))
}

// Fill is the one constructor of a Filled: it fills the template from the fields, checks the
// document against the template and the raw input, and makes the value only where nothing refuses;
// otherwise it answers a *Refusal naming every finding.
func Fill(t *Template, values Object, raw string, title *string, existing string) (Filled, error) {
	document, found, err := FillDocument(t, values, raw, title, existing)
	if err != nil {
		return Filled{}, err
	}
	if Refused(found) {
		return Filled{}, &Refusal{t.Name, found}
	}
	var warnings []Finding
	for _, f := range found {
		if f.Severity != Refuse {
			warnings = append(warnings, f)
		}
	}
	content := filledContent{Template: t.Name, Repository: t.Repository, Version: t.Version, Digest: t.Digest,
		Fields: Answer(t, values), Document: document, Warnings: warnings}
	if title != nil {
		named := *title
		content.Title = &named
	}
	return Filled{content, sealOf(content)}, nil
}

// Accept is the gate of every templated target: it answers the filled template v is, of the
// template named (any template where named is ""), and refuses everything else, naming the template
// to fill. v is a Filled, or its JSON as another component passed it on; free text, a body, field
// values or JSON written by hand are refused.
func Accept(target, named string, v any) (Filled, error) {
	refuse := func(what string) (Filled, error) {
		return Filled{}, &Error{fmt.Sprintf("%s takes a filled template%s, not %s: fill it with the template component's fill (%s), which checks it once and makes the only value %s accepts", target, ofTemplate(named), what, fillHint(named), target)}
	}
	var f Filled
	switch x := v.(type) {
	case Filled:
		f = x
	case *Filled:
		if x == nil {
			return refuse("nothing")
		}
		f = *x
	case string:
		if err := json.Unmarshal([]byte(x), &f); err != nil {
			return refuse("free text")
		}
	case []byte:
		if err := json.Unmarshal(x, &f); err != nil {
			return refuse("free text")
		}
	case nil:
		return refuse("nothing")
	default:
		data, err := json.Marshal(x)
		if err != nil || json.Unmarshal(data, &f) != nil {
			return refuse(fmt.Sprintf("a %T", v))
		}
	}
	if !f.Valid() {
		return refuse("a value of its shape that fill did not make")
	}
	if named != "" && f.Template() != named {
		return refuse(fmt.Sprintf("a filled template of %s", f.Template()))
	}
	return f, nil
}

func ofTemplate(named string) string {
	if named == "" {
		return ""
	}
	return " of " + named
}

func fillHint(named string) string {
	if named == "" {
		return "verb fill of the template component, or `templates.py fill <template>`"
	}
	return fmt.Sprintf("verb fill of the template component with template %s, or `templates.py fill %s`", named, named)
}
