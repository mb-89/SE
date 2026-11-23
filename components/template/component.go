package template

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"kern/index"
)

// Name is the component's name, which the wiring's instances name.
const Name = "template"

// The named JSON shapes of the verbs' requests and answers, so a component in another language asks
// them as a Go one does.
const (
	FillShape    = "template.fill"
	FilledShape  = "template.filled"
	CheckShape   = "template.check"
	CheckedShape = "template.checked"
)

// FillRequest is what the verb fill asks: the template, the agent's field values, the raw input
// they come from and, where the template has one, the title.
type FillRequest struct {
	Template string  `json:"template"`
	Fields   Object  `json:"fields"`
	Raw      string  `json:"raw"`
	Title    *string `json:"title,omitempty"`
}

// CheckRequest is what the verb check asks: a text and its title, against the template named, or,
// without one, the template Select takes for the action.
type CheckRequest struct {
	Template string   `json:"template,omitempty"`
	Action   string   `json:"action,omitempty"`
	Body     string   `json:"body"`
	Title    *string  `json:"title,omitempty"`
	Labels   []string `json:"labels,omitempty"`
}

// Checked is what the verb check answers: the template it checked against ("" where the text is
// free), whether something refuses, and every finding.
type Checked struct {
	Template string    `json:"template"`
	Refused  bool      `json:"refused"`
	Findings []Finding `json:"findings"`
}

type state struct {
	mu         sync.Mutex
	root       string
	repository string
}

var s = state{root: ".", repository: SERepository}

// Catalog reads the templates of the checkout the instance serves: its templates/ folder, each
// marked with the instance's repository. It reads them at each call, so an edited template counts
// at once.
func catalog() (Catalog, error) {
	s.mu.Lock()
	root, repository := s.root, s.repository
	s.mu.Unlock()
	return LoadFolder(filepath.Join(root, TemplatesFolder), repository)
}

// LoadFolder loads the template notes and the term list of one folder, marked with repository.
func LoadFolder(folder, repository string) (Catalog, error) {
	entries, err := os.ReadDir(folder)
	if err != nil {
		return nil, fail("templates: %s does not exist; run from an SE checkout", folder)
	}
	files := map[string]string{}
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !(strings.HasSuffix(name, templateSuffix) || name == TermsFile) {
			continue
		}
		data, err := os.ReadFile(filepath.Join(folder, name))
		if err != nil {
			return nil, err
		}
		files[name] = string(data)
	}
	return Load(Layer{repository, files, func(name string) string { return TemplatesFolder + "/" + name }})
}

func named(templates Catalog, name string) (*Template, error) {
	t, ok := templates[name]
	if !ok {
		return nil, fail("templates: no template %s; the templates are %s", name, joinStrings(sortedKeys(templates)))
	}
	return t, nil
}

// fillVerb is the verb fill: the one place a Filled is made.
func fillVerb(_ context.Context, req FillRequest) (Filled, error) {
	templates, err := catalog()
	if err != nil {
		return Filled{}, err
	}
	t, err := named(templates, req.Template)
	if err != nil {
		return Filled{}, err
	}
	fields := req.Fields
	if fields == nil {
		fields = Object{}
	}
	return Fill(t, fields, req.Raw, req.Title, "")
}

func checkVerb(_ context.Context, req CheckRequest) (Checked, error) {
	templates, err := catalog()
	if err != nil {
		return Checked{}, err
	}
	var t *Template
	var found []Finding
	switch {
	case req.Template != "" && req.Action != "":
		return Checked{}, fail("templates check: give a template or an action, not both")
	case req.Template != "":
		if t, err = named(templates, req.Template); err != nil {
			return Checked{}, err
		}
		found = Check(t, Parse(t, req.Body, req.Title), nil)
	case req.Action != "":
		if t, found, err = Verdict(templates, req.Action, req.Body, req.Title, Where{Labels: req.Labels}); err != nil {
			return Checked{}, err
		}
	default:
		return Checked{}, fail("templates check: give the template, or the action whose template checks the text")
	}
	answer := Checked{Refused: Refused(found), Findings: found}
	if answer.Findings == nil {
		answer.Findings = []Finding{}
	}
	if t != nil {
		answer.Template = t.Name
	}
	return answer, nil
}

// Component is the component a binary carries: SE's template engine, whose verb fill makes the
// filled templates every templated target takes (README "Templates", components/README.md).
var Component = index.Declare(Name, "SE's template engine in Go: fill makes a filled template, the one value a templated target takes, after checking it; check gives a text's findings.",
	index.IO(),
	index.Config("root", ".", "The checkout whose templates/ the engine reads; a detached core runs in its root."),
	index.Config("repository", SERepository, "The repository its templates' marker names: se for SE's own, project for an application's."),
	index.JSONVerb("fill", "Fills a template from the agent's fields and the raw input, checks the document, and answers the filled template, the one value a templated target takes; a fill something refuses answers every finding and makes nothing.", FillShape, FilledShape, fillVerb),
	index.JSONVerb("check", "Checks a text against its template, named or selected by its action, as SE's filing commands would: every finding, and whether one refuses.", CheckShape, CheckedShape, checkVerb),
	index.Inlet(func(_ string, read index.Reader, _ index.Commit) error {
		root, _ := read(index.ConfigPrefix + "root").(string)
		repository, _ := read(index.ConfigPrefix + "repository").(string)
		if repository == "" {
			repository = SERepository
		}
		s.mu.Lock()
		s.root, s.repository = root, repository
		s.mu.Unlock()
		return nil // the templates are read at each call: a checkout without templates/ still starts
	}),
)

func init() { index.Register(Component) }
