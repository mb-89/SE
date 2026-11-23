package template

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"kern/index"
)

// The filled template is a type (SE#1683): only Fill makes one, after checking, and a target that
// requires one refuses everything else.

func workFields(t *testing.T) (*Template, Object, *string) {
	t.Helper()
	work := seTemplates(t)["work"]
	title, _ := work.Example.Value("title").(string)
	return work, work.Example.Value("fields").(Object).Copy(), &title
}

const raw = "The person said: so pass, don't validate."

func TestFillMakesAFilledTemplateOnlyWhereNothingRefuses(t *testing.T) {
	work, fields, title := workFields(t)
	filled, err := Fill(work, fields, raw, title, "")
	if err != nil {
		t.Fatalf("the work template's example does not fill: %v", err)
	}
	document, found, _ := FillDocument(work, fields, raw, title, "")
	if !filled.Valid() || filled.Template() != "work" || filled.Version() != work.Version || filled.Digest() != work.Digest {
		t.Fatalf("the filled template is %+v", filled)
	}
	if filled.Document() != document || len(filled.Warnings()) != len(found) {
		t.Fatalf("the filled template's document or warnings differ from the fill's")
	}
	if got, _ := filled.Title(); got != *title {
		t.Fatalf("the filled template's title is %q", got)
	}

	fields.Set("goal", "TBD")
	refused, err := Fill(work, fields, raw, title, "")
	var refusal *Refusal
	if !asRefusal(err, &refusal) || refused.Valid() {
		t.Fatalf("a fill with an empty goal made %+v, %v", refused, err)
	}
	if !strings.Contains(err.Error(), "goal [required]") || !strings.Contains(err.Error(), "nothing was made") {
		t.Fatalf("the refusal does not name the goal: %v", err)
	}
}

func asRefusal(err error, out **Refusal) bool {
	r, ok := err.(*Refusal)
	*out = r
	return ok
}

func TestATargetRefusesFreeTextWhereAFilledTemplateIsRequired(t *testing.T) {
	work, fields, title := workFields(t)
	filled, err := Fill(work, fields, raw, title, "")
	if err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(filled)
	if err != nil {
		t.Fatal(err)
	}
	forged := strings.Replace(string(data), "## Goal", "## Goal\n\nAdded by hand.", 1)
	hand, _ := json.Marshal(map[string]any{"template": "work", "version": work.Version, "document": filled.Document()})
	for what, v := range map[string]any{
		"free text":            filled.Document(),
		"a body and fields":    map[string]any{"template": "work", "body": filled.Document()},
		"JSON of its shape":    string(hand),
		"a changed document":   forged,
		"the zero value":       Filled{},
		"nothing":              nil,
		"a filled ticket":      nil, // set below
		"a pointer to nothing": (*Filled)(nil),
	} {
		if what == "a filled ticket" {
			ticket := seTemplates(t)["ticket"]
			ticketTitle, _ := ticket.Example.Value("title").(string)
			v, err = Fill(ticket, ticket.Example.Value("fields").(Object), raw, &ticketTitle, "")
			if err != nil {
				t.Fatal(err)
			}
		}
		_, err := Accept("the GitHub door's issue-create", "work", v)
		if err == nil {
			t.Errorf("Accept took %s where a filled work template is required", what)
			continue
		}
		if !strings.Contains(err.Error(), "takes a filled template of work") || !strings.Contains(err.Error(), "fill") {
			t.Errorf("Accept's refusal of %s names no template to fill: %v", what, err)
		}
	}
	for what, v := range map[string]any{"the value": filled, "its JSON": string(data), "a pointer": &filled} {
		got, err := Accept("the GitHub door's issue-create", "work", v)
		if err != nil || got.Document() != filled.Document() {
			t.Errorf("Accept refused %s that fill made: %v", what, err)
		}
	}
	var decoded Filled
	if err := json.Unmarshal([]byte(forged), &decoded); err == nil {
		t.Fatal("a filled template whose document was changed decodes")
	}
}

// kern's typed index refuses the rest by itself: a verb that takes a Filled is never handed a text.
func TestAVerbThatTakesAFilledTemplateIsRefusedFreeTextByKern(t *testing.T) {
	var written []string
	target := index.Declare("target", "A templated target, for this test.", index.IO(),
		index.Verb("write", "Writes a filled template.", func(_ context.Context, f Filled) (string, error) {
			got, err := Accept("target write", "work", f)
			if err != nil {
				return "", err
			}
			written = append(written, got.Document())
			return "written", nil
		}))
	if err := target.Err(); err != nil {
		t.Fatal(err)
	}
	work, fields, title := workFields(t)
	filled, err := Fill(work, fields, raw, title, "")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := target.Serve(context.Background(), "write", filled.Document()); err == nil || !strings.Contains(err.Error(), "template.Filled") {
		t.Fatalf("kern handed the target free text: %v", err)
	}
	if _, err := target.Serve(context.Background(), "write", Filled{}); err == nil {
		t.Fatal("the target took the zero value")
	}
	if answer, err := target.Serve(context.Background(), "write", filled); err != nil || answer != "written" || len(written) != 1 {
		t.Fatalf("the target refused the filled template: %v, %v", answer, err)
	}
}

func startComponent(t *testing.T) {
	t.Helper()
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	config := map[string]any{index.ConfigPrefix + "root": root, index.ConfigPrefix + "repository": SERepository}
	if err := Component.Start("template", func(port string) any { return config[port] }, nil); err != nil {
		t.Fatal(err)
	}
}

func TestTheComponentsVerbFillAnswersASealedFilledTemplate(t *testing.T) {
	startComponent(t)
	work, fields, title := workFields(t)
	answer, err := Component.Serve(context.Background(), "fill", map[string]any{"template": "work", "fields": fields, "raw": raw, "title": *title})
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(answer)
	got, err := Accept("a target", "work", data)
	if err != nil {
		t.Fatalf("the verb's answer is no filled template: %v", err)
	}
	if got.Version() != work.Version {
		t.Fatalf("the verb filled %s %s", got.Template(), got.Version())
	}
	fields.Set("approach", "We do it.")
	_, err = Component.Serve(context.Background(), "fill", map[string]any{"template": "work", "fields": fields, "raw": raw, "title": *title})
	if err == nil || !strings.Contains(err.Error(), "not-picked") {
		t.Fatalf("the verb filled an approach without its alternative: %v", err)
	}
	if _, err := Component.Serve(context.Background(), "fill", map[string]any{"template": "nope"}); err == nil || !strings.Contains(err.Error(), "no template nope") {
		t.Fatalf("the verb filled a template that does not exist: %v", err)
	}
}

func TestTheComponentsVerbCheckGivesATextsFindings(t *testing.T) {
	startComponent(t)
	answer, err := Component.Serve(context.Background(), "check", map[string]any{"action": "issue.create", "body": "## Situation\n\nIt is so.\n"})
	if err != nil {
		t.Fatal(err)
	}
	var checked Checked
	if err := index.Recode(answer, &checked); err != nil {
		t.Fatal(err)
	}
	if checked.Template != "ticket" || !checked.Refused || len(checked.Findings) == 0 {
		t.Fatalf("check answered %+v", checked)
	}
	if _, err := Component.Serve(context.Background(), "check", map[string]any{"body": "x"}); err == nil {
		t.Fatal("check took a text without a template or an action")
	}
}

const risksTemplate = `---
name: risks
version: 1.0.0
kind: document
tags: ["test"]
reader: owner
says: "Risks: what could go wrong."
applies:
  actions: ["file.write"]
  paths: ["book/*/steps/*.md"]
rules:
  required: refuse
fields:
  - name: risks
    kind: list
    required: true
---

## Risks

<!-- risks: One item per risk. -->
`

// The verb accept is the gate a target in another component asks: kern's GitHub door and its files
// module take a filled template through it, and a path no template claims stays free.
func TestTheComponentsVerbAcceptRefusesFreeTextAndTakesAFilledTemplate(t *testing.T) {
	startComponent(t)
	work, fields, title := workFields(t)
	ctx := context.Background()
	filled, err := Component.Serve(ctx, "fill", map[string]any{"template": "work", "fields": fields, "raw": raw, "title": *title})
	if err != nil {
		t.Fatal(err)
	}
	answer, err := Component.Serve(ctx, "accept", map[string]any{"target": "github issue-create", "template": "work", "filled": filled})
	if err != nil {
		t.Fatalf("accept refused the filled template fill made: %v", err)
	}
	var got Accepted
	if err := index.Recode(answer, &got); err != nil || got.Template != "work" || got.Version != work.Version || got.Title == nil || *got.Title != *title || got.Free {
		t.Fatalf("accept answered %+v, %v", got, err)
	}
	document, _, _ := FillDocument(work, fields, raw, title, "")
	if got.Document != document {
		t.Fatal("accept answered another document than the fill rendered")
	}
	for what, v := range map[string]any{"free text": document, "fields": map[string]any{"template": "work", "fields": fields}} {
		_, err := Component.Serve(ctx, "accept", map[string]any{"target": "github issue-create", "template": "work", "filled": v})
		if err == nil || !strings.Contains(err.Error(), "github issue-create takes a filled template of work") {
			t.Errorf("accept took %s: %v", what, err)
		}
	}
}

func TestTheVerbAcceptRequiresTheTemplateThatClaimsAPathAndLeavesOtherPathsFree(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, TemplatesFolder), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, TemplatesFolder, "risks.md"), []byte(risksTemplate), 0o644); err != nil {
		t.Fatal(err)
	}
	config := map[string]any{index.ConfigPrefix + "root": root, index.ConfigPrefix + "repository": ProjectRepository}
	if err := Component.Start("template", func(port string) any { return config[port] }, nil); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { startComponent(t) })
	ctx := context.Background()
	path := filepath.ToSlash(filepath.Join("book", "m1", "steps", "51.md"))
	filled, err := Component.Serve(ctx, "fill", map[string]any{"template": "risks", "fields": map[string]any{"risks": []any{"The scan misses a tool."}}, "raw": "x"})
	if err != nil {
		t.Fatal(err)
	}
	answer, err := Component.Serve(ctx, "accept", map[string]any{"target": "files write", "path": path, "filled": filled})
	var got Accepted
	if err != nil || index.Recode(answer, &got) != nil || got.Template != "risks" || !strings.Contains(got.Document, "- The scan misses a tool.") {
		t.Fatalf("accept refused the filled risks template for %s: %+v, %v", path, got, err)
	}
	_, err = Component.Serve(ctx, "accept", map[string]any{"target": "files write", "path": path, "filled": "## Risks\n\n- Typed by hand.\n"})
	if err == nil || !strings.Contains(err.Error(), "files write of book/m1/steps/51.md takes a filled template of risks") {
		t.Fatalf("accept took free text for a claimed path: %v", err)
	}
	answer, err = Component.Serve(ctx, "accept", map[string]any{"target": "files write", "path": "notes.md", "filled": "anything"})
	if err != nil || index.Recode(answer, &got) != nil || !got.Free {
		t.Fatalf("a path no template claims is not free: %+v, %v", got, err)
	}
}
