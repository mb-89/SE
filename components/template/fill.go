package template

// filling is what a fill made: the document, every finding, every correction and the values it
// filled the template with, corrected, its title aside.
type filling struct {
	document    string
	found       []Finding
	corrections []Correction
	values      Object
}

// FillDocument renders the document values fill the template with and checks it against the raw
// input, as scripts/templates.py's fill does; title fills the title field, existing is the text of a
// file a file template fills again. It answers the document, every finding, refusing or not, and
// every correction the correction pass made (corrections.go).
func FillDocument(t *Template, values Object, raw string, title *string, existing string) (string, []Finding, []Correction, error) {
	f, err := fill(t, values, raw, title, existing, nil)
	return f.document, f.found, f.corrections, err
}

// FillBodyDocument is FillDocument of a whole document the agent wrote, in place of its fields:
// corrected (CorrectBody), its fields are its parse's, and it is filled as an existing text.
func FillBodyDocument(t *Template, body, raw string, title *string) (string, []Finding, []Correction, error) {
	f, err := fill(t, nil, raw, title, "", &body)
	return f.document, f.found, f.corrections, err
}

// fill is templates.py `fill`: body, where given, takes the place of values.
func fill(t *Template, values Object, raw string, title *string, existing string, body *string) (filling, error) {
	if t.IsAdapter() {
		return filling{}, fail("templates: %s is an adapter and has no fields to fill; the command that writes it writes its body", t.Name)
	}
	titleField := ""
	for _, item := range t.Fields {
		if item.Source == "title" {
			titleField = item.Name
			break
		}
	}
	var corrections []Correction
	if body != nil {
		if len(values) > 0 {
			return filling{}, fail("templates: fill %s from its fields or from a body, not both", t.Name)
		}
		var text string
		text, corrections = CorrectBody(t, *body)
		values = Parse(t, text, nil).Read.Copy()
		existing = text
	}
	values, more := Correct(t, Answer(t, values))
	corrections = append(corrections, more...)
	checked := values.Copy()
	if title != nil && titleField != "" {
		values.Set(titleField, *title)
	}
	var rendered string
	var err error
	if existing != "" {
		doc := Parse(t, existing, nil)
		doc.Fields = values.Copy()
		rendered, err = Render(t, doc)
	} else {
		rendered, err = RenderFields(t, values)
	}
	if err != nil {
		return filling{}, err
	}
	rendered = RecordCorrections(t, rendered, corrections)
	var named *string
	if titleField != "" {
		if s, ok := values.Value(titleField).(string); ok {
			named = &s
		}
	}
	found, err := CheckText(t, Parse(t, rendered, named), &raw)
	return filling{rendered, found, corrections, checked}, err
}
