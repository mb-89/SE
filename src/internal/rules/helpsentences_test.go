package rules_test

import (
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/rules"
)

func TestAHelpStringOfMoreThanOneSentenceIsRefused(t *testing.T) {
	t.Parallel()
	found := check(t, "help-sentences", map[string]string{
		"src/a/a.go": "package a\n\n" +
			"var one = Command{Details: []string{\"one sentence, (e.g. this) and usage <word>... (an ellipsis).\", \"Two.\"}}\n" +
			"var plain = Command{Details: \"one sentence alone.\"}\n" +
			"var long = Command{\n\tDetails: []string{\n\t\t\"First. Second.\",\n\t\t\"Fine.\",\n\t},\n}\n" +
			"var decl = CommandDecl{Help: \"It does this. Then that.\"}\n" +
			"var short = CommandDecl{Help: \"It does this.\", Summary: \"a. b\"}\n",
		"src/a/b.txt": "Details: \"First. Second.\"\n",
	})
	same(t, found, []string{
		"src/a/a.go:4: help-sentences: a command's Details are a list of sentences",
		"src/a/a.go:7: help-sentences: a Details string literal holds 2 sentences",
		"src/a/a.go:11: help-sentences: a Help string literal holds 2 sentences",
	})
}

func TestFixSplitsDetailsIntoItsSentences(t *testing.T) {
	t.Parallel()
	d, root := disk.NewFake(), filepath.FromSlash("/checkout")
	files := map[string]string{
		"src/a/a.go": "package a\n\nimport \"fmt\"\n\nconst name = \"N\"\n\n" +
			"var one = Command{\n\tDetails: fmt.Sprintf(\"First %d. Second %s, 100%%.\", 1, \"x\") + \" Third of \" + name + \". Fourth? Yes!\",\n}\n\n" +
			"var two = Command{\n\tDetails: []string{\n\t\t\"Kept.\",\n\t\t\"Split. Here.\",\n\t},\n}\n\n" +
			"var three = Command{Details: \"Alone, 5%.\"}\n",
		"src/b/b.go":  "package b\n\nvar x = Command{Details: \"Needs. \" + name}\n",
		"src/c/ok.go": "package c\n\nvar y = Command{Details: []string{\"Done.\"}}\n",
	}
	var paths []string
	for p, text := range files {
		put(t, d, filepath.Join(root, filepath.FromSlash(p)), text)
		paths = append(paths, p)
	}
	sort.Strings(paths)
	repo := &rules.Repo{Root: root, Disk: d, Paths: paths}
	fixed, err := rules.Fix(repo)
	if err != nil || strings.Join(fixed, ",") != "src/a/a.go: help-sentences,src/b/b.go: help-sentences" {
		t.Fatalf("fixed %q, %v", fixed, err)
	}
	got, _ := d.ReadFile(filepath.Join(root, "src", "a", "a.go"))
	want := "package a\n\nimport \"fmt\"\n\nconst name = \"N\"\n\n" +
		"var one = Command{\n\tDetails: []string{\n" +
		"\t\tfmt.Sprintf(\"First %d.\", 1),\n" +
		"\t\tfmt.Sprintf(\"Second %s, 100%%.\", \"x\"),\n" +
		"\t\tfmt.Sprintf(\"Third of %v.\", name),\n" +
		"\t\t\"Fourth?\",\n\t\t\"Yes!\",\n\t},\n}\n\n" +
		"var two = Command{\n\tDetails: []string{\n\t\t\"Kept.\",\n\t\t\"Split.\",\n\t\t\"Here.\",\n\t},\n}\n\n" +
		"var three = Command{Details: []string{\n\t\"Alone, 5%.\",\n}}\n"
	if string(got) != want {
		t.Fatalf("a.go:\n%s", got)
	}
	got, _ = d.ReadFile(filepath.Join(root, "src", "b", "b.go"))
	if want := "package b\n\nimport \"fmt\"\n\nvar x = Command{Details: []string{\n\t\"Needs.\",\n\tfmt.Sprintf(\"%v\", name),\n}}\n"; string(got) != want {
		t.Fatalf("b.go:\n%s", got)
	}
	if fixed, err := rules.Fix(repo); err != nil || len(fixed) != 0 {
		t.Fatalf("a second fix: %q, %v", fixed, err)
	}
}
