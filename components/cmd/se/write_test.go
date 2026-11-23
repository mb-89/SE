package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"kern/components/clock"
	"kern/components/github"
	"kern/index"
	"se/components/template"
)

// fakeREST is GitHub's REST API in process, no listener: it records each POST and answers it
// with the issue or the comment it made.
type fakeREST struct {
	mu   sync.Mutex
	sent []string
}

func (f *fakeREST) RoundTrip(r *http.Request) (*http.Response, error) {
	body, _ := io.ReadAll(r.Body)
	f.mu.Lock()
	f.sent = append(f.sent, r.Method+" "+r.URL.Path+" "+string(body))
	f.mu.Unlock()
	answer := `{"number": 21, "html_url": "https://github.com/alice/demo/issues/21"}`
	return &http.Response{StatusCode: http.StatusCreated, Header: http.Header{}, Request: r,
		Body: io.NopCloser(strings.NewReader(answer))}, nil
}

func (f *fakeREST) posts() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string{}, f.sent...)
}

// SE's wiring binds the GitHub door's port template-accept to the template component's verb
// accept (kern's components/github README "Writes: filled templates only"): through SE's wiring,
// a write of free text is refused by accept, naming the template to fill, and reaches GitHub not
// at all; the filled template the template component's fill made of SE's work template is
// filed, its title and document as they stand.
func TestSEsWiringFilesOnlyAFilledTemplate(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "..", "wiring.toml"))
	if err != nil {
		t.Fatal(err)
	}
	w, err := index.ParseWiring(data)
	if err != nil {
		t.Fatal(err)
	}
	if wire := wireOf(w, "github.template-accept"); wire != "template.accept" {
		t.Fatalf("SE's wiring binds github.template-accept to %q, and wants template.accept", wire)
	}
	kept := map[string]bool{"github": true, "template": true, "clock": true}
	var instances []index.Instance
	for _, in := range w.Instances {
		if kept[in.Name] {
			if in.Config == nil {
				in.Config = map[string]index.ConfigValue{}
			}
			switch in.Name {
			case "github":
				in.Config["backend"] = index.ConfigValue{Value: github.Token}
				in.Config["api"] = index.ConfigValue{Value: "https://api.github.test"}
			case "template":
				in.Config["root"] = index.ConfigValue{Value: filepath.Join("..", "..", "..")}
			}
			instances = append(instances, in)
		}
	}
	var wires []index.Wire
	for _, wire := range w.Wires {
		if inst, _, _ := strings.Cut(wire.Port, "."); kept[inst] {
			wires = append(wires, wire)
		}
	}
	w.Instances, w.Wires, w.Hooks = instances, wires, nil
	rest := &fakeREST{}
	g := github.New(github.Options{Clock: still{}, Token: func() (string, error) { return "t", nil },
		Client: &http.Client{Transport: rest}})
	ix, err := index.Start(w, clock.New(clock.Options{Clock: still{}}).Component, g.Component, template.Component)
	if err != nil {
		t.Fatal(err)
	}

	for _, free := range []string{`"free text"`, `{"title": "t", "body": "free text"}`} {
		_, err := ix.Call("github issue-create", "--repo", "alice/demo", "--filled", free)
		if err == nil || !strings.Contains(err.Error(), "github issue-create takes a filled template, not") || !strings.Contains(err.Error(), "nothing reached GitHub") {
			t.Fatalf("a write of %s answers %v, and wants accept's refusal naming the fill", free, err)
		}
	}
	if sent := rest.posts(); len(sent) != 0 {
		t.Fatalf("GitHub was sent %v, and wants nothing for free text", sent)
	}

	work, err := template.LoadFolder(filepath.Join("..", "..", "..", template.TemplatesFolder), template.SERepository)
	if err != nil {
		t.Fatal(err)
	}
	title, _ := work["work"].Example.Value("title").(string)
	fields := work["work"].Example.Value("fields").(template.Object).Copy()
	filled, err := template.Component.Serve(context.Background(), "fill",
		map[string]any{"template": "work", "fields": fields, "raw": "The person said: so pass, don't validate.", "title": title})
	if err != nil {
		t.Fatalf("the work template's example does not fill: %v", err)
	}
	value, err := json.Marshal(filled)
	if err != nil {
		t.Fatal(err)
	}
	r, err := ix.Call("github issue-create", "--repo", "alice/demo", "--label", "work", "--filled", string(value))
	if err != nil || r.Text != "filed alice/demo#21: https://github.com/alice/demo/issues/21" {
		t.Fatalf("the filled work template answers %q, %v, and wants it filed", r.Text, err)
	}
	sent := rest.posts()
	var made template.Filled
	if err := json.Unmarshal(value, &made); err != nil {
		t.Fatal(err)
	}
	var payload map[string]any
	if len(sent) != 1 || !strings.HasPrefix(sent[0], "POST /issues ") && !strings.HasPrefix(sent[0], "POST /repos/alice/demo/issues ") {
		t.Fatalf("GitHub was sent %v, and wants one POST of the issue", sent)
	}
	if err := json.Unmarshal([]byte(sent[0][strings.Index(sent[0], "{"):]), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["title"] != title || payload["body"] != made.Document() {
		t.Fatalf("GitHub was sent %v, and wants the filled template's title and document as they stand", payload)
	}
}

func wireOf(w index.Wiring, port string) string {
	for _, wire := range w.Wires {
		if wire.Port == port {
			return wire.To
		}
	}
	return ""
}
