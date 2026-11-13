package gitfake

// The state file: the fake as SE's Python door shares it with the processes
// a test starts (SE_GIT_DOOR=fake:<state file>, written by SE's
// tests/fake_git.py StateFile). This file reads that format; the testdata
// state, which the Python fake writes and both fakes answer alike, holds the
// two readers to one format.

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/mb-89/kern/git"
)

// StateFormat is the format a state file names.
const StateFormat = "se-git-door-state/1"

type stateRepository struct {
	Path   string            `json:"path"`
	Head   string            `json:"head"`
	Refs   map[string]string `json:"refs"`
	Config map[string]string `json:"config"`
	Index  map[string]string `json:"index"`
	Main   string            `json:"main"`
}

type stateCommit struct {
	Tree          string   `json:"tree"`
	Parents       []string `json:"parents"`
	Message       string   `json:"message"`
	Author        []string `json:"author"`
	Committer     []string `json:"committer"`
	CommitterDate string   `json:"committer_date"`
}

type state struct {
	Format       string                       `json:"format"`
	Repositories []stateRepository            `json:"repositories"`
	Trees        map[string]map[string]string `json:"trees"`
	Commits      map[string]stateCommit       `json:"commits"`
}

func init() {
	git.RegisterStateFile(func(path string) git.Backend { return stateFile{path} })
}

// Load answers the fake a state file holds; its paths are relative to the
// file's folder, or absolute, slash-separated either way.
func Load(path string) (*Fake, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var s state
	if err := json.Unmarshal(data, &s); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if s.Format != StateFormat {
		return nil, fmt.Errorf("%s: git door state is %q, not %q", path, s.Format, StateFormat)
	}
	folder := filepath.Dir(canonical(path))
	place := func(p string) string {
		p = filepath.FromSlash(p)
		if !filepath.IsAbs(p) {
			p = filepath.Join(folder, p)
		}
		return canonical(p)
	}
	blobs := func(in map[string]string) (map[string]string, error) {
		out := map[string]string{}
		for name, blob := range in {
			content, err := base64.StdEncoding.DecodeString(blob)
			if err != nil {
				return nil, fmt.Errorf("%s: %s: %w", path, name, err)
			}
			out[name] = string(content)
		}
		return out, nil
	}
	f := New()
	for id, c := range s.Commits {
		tree, err := blobs(s.Trees[c.Tree])
		if err != nil {
			return nil, err
		}
		when, err := time.Parse(time.RFC3339, c.CommitterDate)
		if err != nil {
			return nil, fmt.Errorf("%s: commit %s: %w", path, id, err)
		}
		cm := &commit{tree: tree, message: c.Message, when: when}
		if len(c.Parents) > 0 {
			cm.parent = c.Parents[0]
		}
		copy(cm.author[:], c.Author)
		copy(cm.committer[:], c.Committer)
		f.commits[id] = cm
	}
	for _, sr := range s.Repositories {
		index, err := blobs(sr.Index)
		if err != nil {
			return nil, err
		}
		root := place(sr.Path)
		f.repos[root] = &repository{root: root, head: sr.Head, refs: orEmpty(sr.Refs),
			sym: map[string]string{}, index: index, config: orEmpty(sr.Config)}
	}
	for _, sr := range s.Repositories { // a linked worktree shares its repository's refs and config
		if sr.Main != "" {
			main, ok := f.repos[place(sr.Main)]
			if !ok {
				return nil, fmt.Errorf("%s: %s names a repository the state lacks", path, sr.Path)
			}
			f.repos[place(sr.Path)].refs, f.repos[place(sr.Path)].config = main.refs, main.config
		}
	}
	return f, nil
}

func orEmpty(m map[string]string) map[string]string {
	if m == nil {
		return map[string]string{}
	}
	return m
}

// stateFile is the backend SE_GIT_DOOR=fake:<path> names: it reads the
// state for each command and answers only reads, since what a command
// changes would not reach the file.
type stateFile struct{ path string }

func (s stateFile) Run(ctx context.Context, c git.Command) (string, error) {
	if !reads(c.Args) {
		return "", &git.Error{Command: c, Code: 129, Err: fmt.Errorf("exit status 129"),
			Stderr: "fake git: kern reads a git door state file and changes nothing; " + c.String() + " would\n"}
	}
	f, err := Load(s.path)
	if err != nil {
		return "", &git.Error{Command: c, Code: 128, Err: err, Stderr: err.Error() + "\n"}
	}
	return f.Run(ctx, c)
}

// reads says whether args, past -C and -c, is a command that changes nothing.
func reads(args []string) bool {
	for len(args) >= 2 && (args[0] == "-C" || args[0] == "-c") {
		args = args[2:]
	}
	if len(args) == 0 {
		return false
	}
	switch args[0] {
	case "rev-parse", "diff", "ls-files", "for-each-ref":
		return true
	case "config":
		plain := 0
		for _, a := range args[1:] {
			if !strings.HasPrefix(a, "--") {
				plain++
			}
		}
		return plain == 1
	}
	return false
}
