package stuck_test

import (
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/SE/src/index"
	"github.com/mb-89/SE/src/index/indextest"
	"github.com/mb-89/SE/src/lib/rest"
	"github.com/mb-89/SE/src/modules/issues/stuck"
)

// fake is the module on the fake index, GitHub answering issue 5 of o/r as
// body, every write with {}, and the workspace's origin o/r.
func fake(t *testing.T, body string) *indextest.Fake {
	t.Helper()
	f, err := indextest.New(stuck.Module)
	if err != nil {
		t.Fatal(err)
	}
	answers := map[string]func(any) (any, error){
		"origin": func(any) (any, error) { return "o/r", nil },
		"get": func(r any) (any, error) {
			if p := r.(rest.Get).Path; p != "repos/o/r/issues/5" {
				return nil, fmt.Errorf("no %s (HTTP 404)", p)
			}
			return []byte(body), nil
		},
		"send": func(any) (any, error) { return []byte("{}"), nil },
	}
	for port, fn := range answers {
		if err := f.Answer(port, fn); err != nil {
			t.Fatal(err)
		}
	}
	return f
}

const waiting = `{"number":5,"title":"Stuck","state":"open","html_url":"https://github.com/o/r/issues/5","labels":[{"name":"se"},{"name":"se-final"},{"name":"se-person"}]}`

// A resume records its mark before it takes off se-final and se-person, so
// the issue is back in the queue with its takeover count reset and one more
// attempt; it reads the repository from the workspace's origin.
func TestAResumeRecordsItsMarkThenTakesOffTheLabels(t *testing.T) {
	t.Parallel()
	f := fake(t, waiting)
	text, err := f.Call("issue resume", "5")
	if err != nil || text != "Resumed #5 Stuck: back in the queue, its takeover count reset.\nhttps://github.com/o/r/issues/5" {
		t.Fatalf("%q %v", text, err)
	}
	want := []index.Request{
		{Port: "origin", Value: ""},
		{Port: "get", Value: rest.Get{Path: "repos/o/r/issues/5"}},
		{Port: "send", Value: rest.Send{Method: "POST", Path: "repos/o/r/issues/5/comments", Fields: []rest.Field{rest.F("body", stuck.ResumeNote)}}},
		{Port: "send", Value: rest.Send{Method: "DELETE", Path: "repos/o/r/issues/5/labels/se-final"}},
		{Port: "send", Value: rest.Send{Method: "DELETE", Path: "repos/o/r/issues/5/labels/se-person"}},
	}
	if got := f.Asked(); !reflect.DeepEqual(got, want) {
		t.Fatalf("asked %+v", got)
	}
}

// --repo names the repository, so the origin is not asked; --json answers
// the data.
func TestAResumeOfANamedRepositoryAnswersJSON(t *testing.T) {
	t.Parallel()
	f := fake(t, `{"number":5,"title":"Stuck","state":"open","labels":[{"name":"se-person"}]}`)
	text, err := f.Call("issue resume", "#5", "--repo", "o/r", "--json")
	if err != nil || text != `{"number":5,"resumed":true}` {
		t.Fatalf("%q %v", text, err)
	}
	if got := f.Asked(); len(got) != 3 || got[0].Port != "get" || got[2].Value.(rest.Send).Path != "repos/o/r/issues/5/labels/se-person" {
		t.Fatalf("asked %+v", got)
	}
}

// Only an open issue waiting on a person is resumed: anything else is
// refused and nothing is written.
func TestOnlyAnIssueWaitingOnAPersonIsResumed(t *testing.T) {
	t.Parallel()
	for name, body := range map[string]string{
		"no person label": `{"number":5,"state":"open","labels":[{"name":"se"}]}`,
		"closed":          `{"number":5,"state":"closed","labels":[{"name":"se-person"}]}`,
		"a pull request":  `{"number":5,"state":"open","pull_request":{},"labels":[{"name":"se-person"}]}`,
	} {
		f := fake(t, body)
		if _, err := f.Call("issue resume", "5"); err == nil || !strings.Contains(err.Error(), "not an open issue waiting on a person") {
			t.Fatalf("%s: %v", name, err)
		}
		for _, r := range f.Asked() {
			if r.Port == "send" {
				t.Fatalf("%s: wrote %+v", name, r)
			}
		}
	}
}

// A failed read fails the resume with GitHub's reason, and writes nothing.
func TestAFailedReadFailsTheResume(t *testing.T) {
	t.Parallel()
	f := fake(t, waiting)
	if _, err := f.Call("issue resume", "6"); err == nil || !strings.Contains(err.Error(), "HTTP 404") {
		t.Fatalf("%v", err)
	}
	if err := f.Answer("origin", func(any) (any, error) { return nil, errors.New("origin names no OWNER/NAME") }); err != nil {
		t.Fatal(err)
	}
	if _, err := f.Call("issue resume", "5"); err == nil || !strings.Contains(err.Error(), "no OWNER/NAME") {
		t.Fatalf("%v", err)
	}
}

// The marks of an issue's comments, oldest first: the highest takeover
// round, the head a conflict takeover found, the first comment of each
// round, the person mark, and a resume that clears them all.
func TestTheMarksCountTakeoversUntilAResume(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	var m stuck.Marks
	for k, c := range []stuck.Comment{
		{ID: 3, Body: "<!-- se:takeover 1 -->", Created: at},
		{ID: 2, Body: "<!-- se:takeover 1 -->", Created: at.Add(time.Minute)},
		{ID: 4, Body: "<!-- se:takeover 2 -->\n<!-- se:takeover-head abc1 -->", Created: at.Add(2 * time.Minute)},
		{ID: 5, Body: "<!-- se:person -->\nStuck twice.", Created: at.Add(3 * time.Minute)},
	} {
		if m.Read(c) {
			t.Fatalf("comment %d resumed", k)
		}
	}
	if m.Takeovers != 2 || m.Head != "abc1" || !m.LastTakeover.Equal(at.Add(2*time.Minute)) || m.Winners[1] != 2 || m.Winners[2] != 4 || !strings.Contains(m.Person, "Stuck twice.") {
		t.Fatalf("%+v", m)
	}
	if !stuck.PersonMarked(m.Person) || stuck.PersonMarked("<!-- se:takeover 1 -->") {
		t.Fatal("PersonMarked read the marks wrong")
	}
	if !m.Read(stuck.Comment{ID: 6, Body: stuck.ResumeNote}) || m.Takeovers != 0 || m.Person != "" || len(m.Winners) != 0 {
		t.Fatalf("after a resume: %+v", m)
	}
}

// A claim is quiet once neither a push nor a takeover moved it for longer
// than the window; the later of the two is when it moved.
func TestAClaimIsQuietPastTheWindowSinceItLastMoved(t *testing.T) {
	t.Parallel()
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	pushed, took := now.Add(-5*time.Hour), now.Add(-time.Hour)
	if quiet, moved := stuck.Quiet(now, pushed, time.Time{}, stuck.Lease); !quiet || !moved.Equal(pushed) {
		t.Fatalf("pushed 5h ago: %v %v", quiet, moved)
	}
	if quiet, moved := stuck.Quiet(now, pushed, took, stuck.Lease); quiet || !moved.Equal(took) {
		t.Fatalf("taken over 1h ago: %v %v", quiet, moved)
	}
}
