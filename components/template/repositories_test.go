package template

import (
	"context"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"

	"kern/git"
)

// caseGit is the git a repository case gives (tests/template_cases.py CaseGit): each clone's HEAD and
// what origin's refs hold; any other command fails, as git without a repository does.
type caseGit struct {
	root string
	c    Object
}

func (g caseGit) Run(_ context.Context, cmd git.Command) (string, error) {
	dir, args := cmd.Dir, cmd.Args
	if len(args) > 1 && args[0] == "-C" {
		dir, args = args[1], args[2:]
	}
	relative := ""
	if rel, err := filepath.Rel(g.root, dir); err == nil && !strings.HasPrefix(rel, "..") {
		relative = filepath.ToSlash(rel)
	}
	refuse := func(stderr string) (string, error) {
		return "", &git.Error{Command: cmd, Code: 128, Stderr: stderr, Err: os.ErrInvalid}
	}
	if len(args) == 2 && args[0] == "rev-parse" && args[1] == "HEAD" && relative != "" {
		heads, _ := g.c.Value("heads").(Object)
		if head, ok := heads.Value(strings.TrimPrefix(relative, "app/")).(string); ok {
			return head + "\n", nil
		}
		return refuse("fatal: not a git repository\n")
	}
	origin := Object{}
	if relative == "app" {
		origin, _ = g.c.Value("origin").(Object)
	}
	if len(args) == 6 && args[0] == "ls-tree" && args[1] == "-r" && args[2] == "--name-only" {
		if files, ok := origin.Value(args[3]).(Object); ok {
			var paths []string
			for _, pair := range files {
				if strings.HasPrefix(pair.Key, args[5]+"/") {
					paths = append(paths, pair.Key)
				}
			}
			sort.Strings(paths)
			listed := ""
			for _, path := range paths {
				listed += path + "\n"
			}
			return listed, nil
		}
	}
	if len(args) == 2 && args[0] == "show" {
		if ref, path, ok := strings.Cut(args[1], ":"); ok {
			if files, ok := origin.Value(ref).(Object); ok {
				if text, ok := files.Value(path).(string); ok {
					return text, nil
				}
			}
		}
	}
	return refuse("fatal: Not a valid object name " + args[len(args)-1] + "\n")
}

// The Go component resolves a project's templates as templates.py `catalog` does: its own at
// origin's integration branch or in its working tree, then each pinned template repository, then
// SE's, and refuses each pin that does not resolve with the Python engine's words.
func TestTemplateRepositoriesResolveAsThePythonEnginesCatalog(t *testing.T) {
	set, ok := readCases(t)["repositories.json"]
	if !ok {
		t.Fatal("no repositories.json among the shared cases")
	}
	se, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	c := &checker{t: t}
	cases := set.Value("cases").([]any)
	for _, item := range cases {
		cs := item.(Object)
		name := cs.Value("name").(string)
		tmp, err := filepath.EvalSymlinks(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		for _, pair := range cs.Value("files").(Object) {
			path := filepath.Join(tmp, filepath.FromSlash(pair.Key))
			if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte(pair.Value.(string)), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		local := filepath.Join(tmp, "machine", ".se", "local.toml")
		if text, ok := cs.Value("local").(string); ok {
			if err := os.MkdirAll(filepath.Dir(local), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(local, []byte(text), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		saved := localConfig
		localConfig = func() string { return local }
		restore := git.Use(caseGit{tmp, cs})
		catalog, err := CatalogAt(filepath.Join(tmp, "app"), ProjectRepository, se)
		restore()
		localConfig = saved
		if want, ok := cs.Get("error"); ok {
			got := "<resolves>"
			if err != nil {
				got = strings.ReplaceAll(filepath.ToSlash(err.Error()), filepath.ToSlash(tmp), "<tmp>")
			}
			c.same(name, "error", got, want.(string))
			continue
		}
		if err != nil {
			c.same(name, "error", err.Error(), "")
			continue
		}
		got := []any{}
		for _, key := range sortedKeys(catalog) {
			tmpl := catalog[key]
			got = append(got, []any{tmpl.Name, tmpl.Repository, tmpl.Path, tmpl.Digest})
		}
		c.same(name, "templates", asJSON(got), asJSON(cs.Value("templates")))
	}
	if c.failed > 0 {
		t.Errorf("%d of %d resolutions differ from the Python engine's", c.failed, len(cases))
	}
}
