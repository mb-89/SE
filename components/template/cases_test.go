package template

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// The shared cases (tests/template_cases.py): the Python engine's answers, which the Go engine
// gives too, word for word.

func casesFolder() string { return filepath.Join("testdata", "cases") }

func readCases(t *testing.T) map[string]Object {
	t.Helper()
	entries, err := os.ReadDir(casesFolder())
	if err != nil {
		t.Fatalf("the shared cases: %v; run `uv run python tests/template_cases.py`", err)
	}
	sets := map[string]Object{}
	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(casesFolder(), entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		v, err := decodeJSON(string(data))
		if err != nil {
			t.Fatalf("%s: %v", entry.Name(), err)
		}
		sets[entry.Name()] = v.(Object)
	}
	if len(sets) == 0 {
		t.Fatal("no shared cases; run `uv run python tests/template_cases.py`")
	}
	return sets
}

func seTemplates(t *testing.T) Catalog {
	t.Helper()
	folder := filepath.Join("..", "..", TemplatesFolder)
	files := map[string]string{}
	entries, err := os.ReadDir(folder)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasSuffix(name, templateSuffix) || name == TermsFile {
			data, err := os.ReadFile(filepath.Join(folder, name))
			if err != nil {
				t.Fatal(err)
			}
			files[name] = string(data)
		}
	}
	catalog, err := Load(Layer{SERepository, files, func(name string) string { return TemplatesFolder + "/" + name }})
	if err != nil {
		t.Fatalf("SE's templates do not load in Go: %v", err)
	}
	return catalog
}

func fixtureFiles(set Object) map[string]string {
	files := map[string]string{}
	for _, pair := range set.Value("files").(Object) {
		files[pair.Key] = pair.Value.(string)
	}
	return files
}

func loadFixture(files map[string]string) (Catalog, error) {
	return Load(Layer{ProjectRepository, files, func(name string) string { return TemplatesFolder + "/" + name }})
}

func asJSON(v any) string {
	data, err := json.Marshal(v)
	if err != nil {
		return "<" + err.Error() + ">"
	}
	return string(data)
}

func findingsJSON(found []Finding) string {
	rows := []any{}
	for _, f := range found {
		rows = append(rows, []any{f.Field, f.Rule, f.Severity, f.Fix})
	}
	return asJSON(rows)
}

func digest(text string) string {
	sum := sha256.Sum256([]byte(text))
	return "sha256:" + hex.EncodeToString(sum[:])
}

func optional(v any) *string {
	if s, ok := v.(string); ok {
		return &s
	}
	return nil
}

type checker struct {
	t      *testing.T
	failed int
}

func (c *checker) same(where, what, got, want string) {
	c.t.Helper()
	if got == want {
		return
	}
	c.failed++
	if c.failed <= 40 {
		c.t.Errorf("%s: %s differs from the Python engine's\n go:     %s\n python: %s", where, what, got, want)
	}
}

func TestTheGoEngineGivesThePythonEnginesAnswers(t *testing.T) {
	sets := readCases(t)
	se := seTemplates(t)
	c := &checker{t: t}
	ran := 0
	basesOf := map[string]map[string]string{}
	files := sortedKeys(sets)
	sort.SliceStable(files, func(i, j int) bool {
		return !sets[files[i]].Has("select") || len(sets[files[i]].Value("templates").(Object)) > 0 && sets[files[j]].Has("select") && len(sets[files[j]].Value("templates").(Object)) == 0
	})
	for _, file := range files {
		set := sets[file]
		if set.Value("set") == "load-errors" {
			continue
		}
		catalog := se
		if set.Has("files") {
			var err error
			catalog, err = loadFixture(fixtureFiles(set))
			if err != nil {
				t.Fatalf("%s: does not load in Go: %v", file, err)
			}
		}
		setName := set.Value("set").(string)
		if basesOf[setName] == nil {
			basesOf[setName] = map[string]string{}
		}
		bases := basesOf[setName]
		templates, _ := set.Value("templates").(Object)
		for _, pair := range templates {
			entry := pair.Value.(Object)
			tmpl := catalog[pair.Key]
			if tmpl == nil {
				t.Errorf("%s: Go loads no template %s", file, pair.Key)
				continue
			}
			ran += checkTemplate(c, file, tmpl, entry, bases)
		}
		if selects, ok := set.Value("select").([]any); ok {
			for _, s := range selects {
				ran += checkSelect(c, file, catalog, s.(Object), bases, se)
			}
		}
		if selects, ok := set.Value("files_select").([]any); ok {
			for i, s := range selects {
				ran++
				cs := s.(Object)
				path := cs.Value("path").(string)
				chosen, err := Select(catalog, FileAction, cs.Value("body").(string), nil, Where{Path: &path})
				where := file + " files_select " + itoa(i)
				if err != nil {
					c.same(where, "error", err.Error(), "")
					continue
				}
				c.same(where, "selected", chosen.Name(), plainText(cs.Value("selected")))
				c.same(where, "findings", findingsJSON(chosen.Findings), asJSON(cs.Value("findings")))
			}
		}
		if existing, ok := set.Value("existing").([]any); ok {
			for i, e := range existing {
				ran++
				cs := e.(Object)
				where := file + " existing " + itoa(i)
				fields := cs.Value("fields").(Object)
				document, found, err := FillDocument(catalog["risks"], fields, "The person asked: keep the raw text, please. Ship it \"standard\".", nil, cs.Value("existing").(string))
				if err != nil {
					c.same(where, "error", err.Error(), "")
					continue
				}
				c.same(where, "document", document, cs.Value("document").(string))
				c.same(where, "findings", findingsJSON(found), asJSON(cs.Value("findings")))
			}
		}
	}
	if c.failed > 0 {
		t.Errorf("%d of %d answers differ from the Python engine's", c.failed, ran)
	}
	t.Logf("%d shared cases", ran)
}

func itoa(i int) string { return strings.TrimSpace(strings.Repeat(" ", 0) + jsonInt(i)) }

func jsonInt(i int) string { data, _ := json.Marshal(i); return string(data) }

func checkTemplate(c *checker, file string, tmpl *Template, entry Object, bases map[string]string) int {
	where := file + " " + tmpl.Name
	info := entry.Value("template").(Object)
	c.same(where, "version", tmpl.Version, info.Value("version").(string))
	c.same(where, "kind", tmpl.Kind, info.Value("kind").(string))
	c.same(where, "digest", tmpl.Digest, info.Value("digest").(string))
	c.same(where, "marker", tmpl.MarkerLine(), info.Value("marker").(string))
	c.same(where, "repository", tmpl.Repository, info.Value("repository").(string))
	c.same(where, "actions", asJSON(toAny(tmpl.Actions)), asJSON(info.Value("actions")))
	c.same(where, "list line", ListLine(tmpl), info.Value("list").(string))
	fields := []any{}
	for _, item := range tmpl.Fields {
		shape := FieldShape(item)
		shape = append(shape, Pair{"name", item.Name}, Pair{"says", item.Says})
		fields = append(fields, shape)
	}
	c.same(where, "fields", asJSON(fields), asJSON(info.Value("fields")))
	ran := 1
	if tmpl.IsAdapter() {
		return ran
	}
	c.same(where, "draft", Draft(tmpl), info.Value("draft").(string))
	c.same(where, "draft_fields", asJSON(DraftFields(tmpl)), asJSON(info.Value("draft_fields")))
	example, _ := entry.Value("example").(Object)
	for i, f := range entry.Value("fills").([]any) {
		ran++
		cs := f.(Object)
		at := where + " fill " + itoa(i)
		values := Object{}
		drop := plainText(cs.Value("drop"))
		for _, pair := range example {
			if pair.Key != drop {
				values = append(values, Pair{pair.Key, copyValue(pair.Value)})
			}
		}
		for _, pair := range cs.Value("change").(Object) {
			values.Set(pair.Key, copyValue(pair.Value))
		}
		at += " (change " + asJSON(cs.Value("change")) + " drop " + drop + " title " + asJSON(cs.Value("title")) + ")"
		document, found, err := FillDocument(tmpl, values, cs.Value("raw").(string), optional(cs.Value("title")), "")
		if want, ok := cs.Get("error"); ok {
			got := ""
			if err != nil {
				got = err.Error()
			}
			c.same(at, "error", got, want.(string))
			continue
		}
		if err != nil {
			c.same(at, "error", err.Error(), "")
			continue
		}
		if want, ok := cs.Get("document"); ok {
			c.same(at, "document", document, want.(string))
			bases[tmpl.Name] = document
			named := optional(cs.Value("title"))
			c.same(at, "parsed", asJSON(Parse(tmpl, document, titled(tmpl, named, values)).Fields), asJSON(cs.Value("parsed")))
		}
		c.same(at, "document digest", digest(document), cs.Value("digest").(string))
		c.same(at, "findings", findingsJSON(found), asJSON(cs.Value("findings")))
	}
	for i, b := range entry.Value("bodies").([]any) {
		ran++
		cs := b.(Object)
		at := where + " body " + itoa(i)
		body := cs.Value("body").(string)
		doc := Parse(tmpl, body, optional(cs.Value("title")))
		c.same(at, "fields", asJSON(doc.Fields), asJSON(cs.Value("fields")))
		misses := sortedKeys(doc.Misses)
		c.same(at, "misses", asJSON(toAny(misses)), asJSON(cs.Value("misses")))
		c.same(at, "recorded", doc.Recorded, cs.Value("recorded").(string))
		c.same(at, "findings", findingsJSON(Check(tmpl, doc, nil)), asJSON(cs.Value("findings")))
		rendered, err := Render(tmpl, doc)
		if err != nil {
			c.same(at, "render", err.Error(), "")
			continue
		}
		c.same(at, "render digest", digest(rendered), cs.Value("render").(string))
	}
	return ran
}

// titled is the title a fill parses its document back with: the one given, else the title field's.
func titled(tmpl *Template, given *string, values Object) *string {
	if given != nil {
		return given
	}
	for _, item := range tmpl.Fields {
		if item.Source == "title" {
			return optional(values.Value(item.Name))
		}
	}
	return nil
}

func checkSelect(c *checker, file string, catalog Catalog, cs Object, bases map[string]string, se Catalog) int {
	bodyOf := cs.Value("body_of").(string)
	body := "Free text.\n"
	if bodyOf != "" {
		body = bases[bodyOf]
	}
	where := Where{Labels: stringsOf(cs.Value("labels")), Base: optional(cs.Value("base"))}
	if repo, ok := cs.Get("repo"); ok {
		r := repo.(string)
		where.Repo, where.Home = &r, stringsOf(cs.Value("home"))
	}
	at := file + " select " + asJSON(cs)
	chosen, err := Select(catalog, cs.Value("action").(string), body, nil, where)
	if err != nil {
		c.same(at, "error", err.Error(), "")
		return 1
	}
	c.same(at, "selected", chosen.Name(), plainText(cs.Value("selected")))
	c.same(at, "findings", findingsJSON(chosen.Findings), asJSON(cs.Value("findings")))
	return 1
}

func TestATemplateThatBreaksTheFormatDoesNotLoadWithThePythonEnginesError(t *testing.T) {
	sets := readCases(t)
	set, ok := sets["load-errors.json"]
	if !ok {
		t.Fatal("no load-errors.json among the shared cases")
	}
	c := &checker{t: t}
	errors := set.Value("errors").([]any)
	for _, e := range errors {
		cs := e.(Object)
		_, err := loadFixture(fixtureFiles(cs))
		got := "<loads>"
		if err != nil {
			got = err.Error()
		}
		c.same(cs.Value("name").(string), "load error", got, cs.Value("error").(string))
	}
	if c.failed > 0 {
		t.Errorf("%d of %d load errors differ from the Python engine's", c.failed, len(errors))
	}
}

func TestEveryOneOfSEsTemplatesLoadsInGo(t *testing.T) {
	catalog := seTemplates(t)
	names := sortedKeys(catalog)
	sort.Strings(names)
	if len(names) < 17 {
		t.Fatalf("Go loads %d of SE's templates: %v", len(names), names)
	}
}
