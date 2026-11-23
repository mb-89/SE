package template

// FillDocument renders the document values fill the template with and checks it against the raw
// input, as scripts/templates.py's fill does; title fills the title field, existing is the text of a
// file a file template fills again. It answers the document and every finding, refusing or not.
func FillDocument(t *Template, values Object, raw string, title *string, existing string) (string, []Finding, error) {
	if t.IsAdapter() {
		return "", nil, fail("templates: %s is an adapter and has no fields to fill; the command that writes it writes its body", t.Name)
	}
	values = Answer(t, values)
	titleField := ""
	for _, item := range t.Fields {
		if item.Source == "title" {
			titleField = item.Name
			break
		}
	}
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
		return "", nil, err
	}
	var named *string
	if titleField != "" {
		if s, ok := values.Value(titleField).(string); ok {
			named = &s
		}
	}
	return rendered, Check(t, Parse(t, rendered, named), &raw), nil
}
