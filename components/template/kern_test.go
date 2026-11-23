package template

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"kern/form"
)

// kernCases is testdata/cases/kern.json, which tests/template_cases.py writes from the Python
// engine: each of SE's templates that kern's GitHub component can file, as se_templates.kern_template
// writes it, and each fill nothing refuses, its fields as se_templates.kern_fields gives them and the
// digest of the document SE renders and checks.
type kernCases struct {
	Kern map[string]struct {
		Template json.RawMessage `json:"template"` // raw, so field_shape keeps its order
		Fills    []struct {
			Title    *string        `json:"title"`
			Fields   map[string]any `json:"fields"`
			Set      map[string]any `json:"set"`
			Unset    []string       `json:"unset"`
			Error    string         `json:"error"`
			Digest   string         `json:"digest"`
			Document string         `json:"document"`
		} `json:"fills"`
	} `json:"kern"`
}

// What kern's GitHub component files is what SE's fill checked: for every fill of every SE
// template kern can file, kern's check (kern/form, the code its write verbs run) refuses none of
// the fields SE hands it, and kern's render of them is the document SE's engine rendered and
// checked, byte for byte (docs/templates.md "Fill").
func TestKernFilesTheDocumentSEsFillChecked(t *testing.T) {
	data, err := os.ReadFile(filepath.Join(casesFolder(), "kern.json"))
	if err != nil {
		t.Fatalf("the kern cases: %v; run `uv run python tests/template_cases.py`", err)
	}
	var cases kernCases
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	if _, ok := cases.Kern["work"]; !ok {
		t.Fatalf("the kern cases hold no work template, and want it: SE files its work issues through kern")
	}
	ran := 0
	for name, c := range cases.Kern {
		tmpl, err := form.ParseTemplate(c.Template)
		if err != nil {
			t.Errorf("%s: kern does not read SE's template: %v", name, err)
			continue
		}
		action := form.IssueCreate
		if !slices.Contains(tmpl.Actions, action) {
			action = form.CommentCreate
		}
		var base map[string]any
		for i, f := range c.Fills {
			if f.Error != "" {
				continue
			}
			fields := f.Fields
			if fields != nil {
				base = fields
			} else {
				fields = map[string]any{}
				for k, v := range base {
					if !slices.Contains(f.Unset, k) {
						fields[k] = v
					}
				}
				for k, v := range f.Set {
					fields[k] = v
				}
			}
			ran++
			if found := tmpl.Check(action, fields); len(found) > 0 {
				t.Errorf("%s fill %d: kern refuses the fill SE's check passed: %q", name, i, found)
				continue
			}
			_, body := tmpl.Render(fields)
			if digest(body) != f.Digest {
				if f.Document != "" {
					t.Errorf("%s fill %d: kern renders\n%s\nand SE checked\n%s", name, i, body, f.Document)
				} else {
					t.Errorf("%s fill %d (fields %v): kern renders\n%s\nand not the document SE checked", name, i, fields, body)
				}
			}
		}
	}
	if ran == 0 {
		t.Fatal("no kern fill ran")
	}
}
