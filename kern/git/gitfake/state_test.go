package gitfake_test

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mb-89/kern/git"
	_ "github.com/mb-89/kern/git/gitfake" // registers the state-file reader
)

// The state file SE's Python fake writes (testdata/state, which SE's
// tests/test_git_door.py holds to what that fake writes) is answered by the
// backend SE_GIT_DOOR=fake:<state file> names as the Python fake answers it
// (answers.json), so the two readers hold to one format.
func TestTheStateFileThePythonFakeWritesAnswersAlike(t *testing.T) {
	folder := filepath.Join("testdata", "state")
	data, err := os.ReadFile(filepath.Join(folder, "answers.json"))
	if err != nil {
		t.Fatal(err)
	}
	var answers []struct {
		Args []string `json:"args"`
		Out  string   `json:"out"`
	}
	if err := json.Unmarshal(data, &answers); err != nil || len(answers) == 0 {
		t.Fatalf("answers.json: %v", err)
	}
	door := git.FromEnvironment("fake:" + filepath.Join(folder, "git-door.json"))
	for _, a := range answers {
		out, err := door.Run(context.Background(), git.Command{Dir: filepath.Join(folder, "repo"), Args: a.Args})
		if err != nil || out != a.Out {
			t.Errorf("git %s answers %q, %v; the Python fake answers %q", strings.Join(a.Args, " "), out, err, a.Out)
		}
	}
	commit := git.Command{Dir: filepath.Join(folder, "repo"), Args: []string{"-c", "user.name=alice", "commit", "-m", "x"}}
	var refused *git.Error
	if _, err := door.Run(context.Background(), commit); !errors.As(err, &refused) || refused.Code != 129 ||
		!strings.Contains(refused.Stderr, "changes nothing") {
		t.Errorf("a commit through the state file answers %v", err)
	}
}

// The variable names real git, a refusal, or the fake; anything else is
// refused, naming the variable.
func TestTheVariableNamesTheBackend(t *testing.T) {
	if reflect.TypeOf(git.FromEnvironment("real")) != reflect.TypeOf(git.Real{}) || git.FromEnvironment("") != nil {
		t.Fatal("real and unset are not real git and the default")
	}
	for value, says := range map[string]string{"refused": "may not run git", "other": "none of real"} {
		_, err := git.FromEnvironment(value).Run(context.Background(), git.Command{Args: []string{"status"}})
		var refused *git.Error
		if !errors.As(err, &refused) || !strings.Contains(refused.Stderr, says) {
			t.Errorf("%s=%s answers %v", git.Variable, value, err)
		}
	}
	t.Setenv(git.Variable, "fake:"+filepath.Join("testdata", "state", "git-door.json"))
	out, err := git.Run(context.Background(), filepath.Join("testdata", "state", "repo"), "rev-parse", "HEAD")
	if err != nil || len(strings.TrimSpace(out)) != 40 {
		t.Fatalf("the door under the variable answers %q, %v", out, err)
	}
}
