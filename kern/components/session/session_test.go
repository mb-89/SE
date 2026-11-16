package session_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"kern/components/session"
	"kern/host"
	"kern/index"
)

var nine = time.Date(2026, 11, 14, 9, 0, 0, 123456789, time.UTC)

// on is the overlay entry that switches the record on, with extra config lines.
func on(t *testing.T, extra string) index.Wiring {
	t.Helper()
	w, err := index.ParseWiring([]byte("[instances.session]\ncomponent = \"session\"\n" + extra))
	if err != nil {
		t.Fatal(err)
	}
	return w
}

// started is the component over dir, started from w, at nine.
func started(t *testing.T, dir string, w index.Wiring) (*index.Index, error) {
	t.Helper()
	s := session.New(session.Options{Dir: dir, Now: func() time.Time { return nine }})
	return index.Start(w, s.Component)
}

func lines(t *testing.T, path string) []string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	sc := bufio.NewScanner(bytes.NewReader(data))
	sc.Buffer(nil, 1<<22)
	for sc.Scan() {
		out = append(out, sc.Text())
	}
	return out
}

func TestThreeEventsOfTwoSessionsGiveTwoFilesInOrder(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "sessions")
	ix, err := started(t, dir, on(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range []struct{ event, payload string }{
		{"Start", `{"session_id": "s1", "n": 1}`},
		{"Start", `{"session_id": "s2"}`},
		{"Tool", `{"session_id": "s1", "n": 2}`},
	} {
		if err := ix.Hear(e.event, []byte(e.payload)); err != nil {
			t.Fatal(err)
		}
	}
	got := lines(t, filepath.Join(dir, "s1.jsonl"))
	want := []string{
		`{"time":"2026-11-14T09:00:00.123456789Z","event":"Start","session":"s1","payload":{"session_id":"s1","n":1}}`,
		`{"time":"2026-11-14T09:00:00.123456789Z","event":"Tool","session":"s1","payload":{"session_id":"s1","n":2}}`,
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("s1.jsonl holds\n%s\nand wants\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if got := lines(t, filepath.Join(dir, "s2.jsonl")); len(got) != 1 || !strings.Contains(got[0], `"event":"Start","session":"s2"`) {
		t.Fatalf("s2.jsonl holds %q, and wants its one Start", got)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 2 {
		t.Fatalf("the folder holds %d files, and wants 2", len(entries))
	}
}

func TestLineCompactsAPayloadAndKeepsOneThatIsNoJSONAsAString(t *testing.T) {
	pretty := []byte("{\n  \"session_id\": \"s1\",\n  \"tool_input\": {\n    \"a\": [1, 2]\n  }\n}\n")
	file, line := session.Line(nine, "E", pretty, true)
	var compact bytes.Buffer
	if err := json.Compact(&compact, pretty); err != nil {
		t.Fatal(err)
	}
	if file != "s1.jsonl" || bytes.Count(line, []byte("\n")) != 1 || !bytes.HasSuffix(line, []byte("\n")) || !bytes.Contains(line, compact.Bytes()) {
		t.Fatalf("Line answers %s and %q, and wants s1.jsonl and one line holding %s", file, line, compact.Bytes())
	}
	file, line = session.Line(nine, "E", []byte("not json\n"), true)
	var v struct {
		Session string `json:"session"`
		Payload any    `json:"payload"`
	}
	if err := json.Unmarshal(line, &v); err != nil || file != "unknown.jsonl" || v.Payload != "not json\n" || v.Session != "" {
		t.Fatalf("Line answers %s and %s, and wants unknown.jsonl with the payload as a string", file, line)
	}
}

func TestAnIDThatIsNoSafeFileNameGoesToUnknown(t *testing.T) {
	for _, payload := range []string{
		`{"tool": "x"}`,
		`{"session_id": "a/b"}`,
		`{"session_id": "` + strings.Repeat("a", 129) + `"}`,
		`{"session_id": ".."}`,
		`{"session_id": 7}`,
	} {
		if file, _ := session.Line(nine, "E", []byte(payload), true); file != "unknown.jsonl" {
			t.Errorf("Line of %s answers %s, and wants unknown.jsonl", payload, file)
		}
	}
	if file, _ := session.Line(nine, "E", []byte(`{"session_id": "`+strings.Repeat("a", 128)+`"}`), true); file != strings.Repeat("a", 128)+".jsonl" {
		t.Errorf("an id of 128 characters goes to %s, and wants its own file", file)
	}
	_, line := session.Line(nine, "E", []byte(`{"session_id": "a/b"}`), true)
	if !bytes.Contains(line, []byte(`"session":"a/b"`)) {
		t.Errorf("the line %s wants the id as given", line)
	}
}

func TestPastMaxBytesEachLineIsShort(t *testing.T) {
	dir := t.TempDir()
	ix, err := started(t, dir, on(t, "config.max-bytes = 150\n"))
	if err != nil {
		t.Fatal(err)
	}
	payload := `{"session_id": "s1", "text": "` + strings.Repeat("x", 40) + `"}`
	for i := 0; i < 3; i++ {
		if err := ix.Hear("E", []byte(payload)); err != nil {
			t.Fatal(err)
		}
	}
	got := lines(t, filepath.Join(dir, "s1.jsonl"))
	if len(got) != 3 || !strings.Contains(got[0], `"payload"`) {
		t.Fatalf("s1.jsonl holds %q, and wants three lines, the first full", got)
	}
	want := `{"time":"2026-11-14T09:00:00.123456789Z","event":"E","session":"s1","dropped":` + jsonInt(len(payload)) + `}`
	for _, l := range got[1:] {
		if l != want {
			t.Fatalf("a line past max-bytes is %s, and wants %s", l, want)
		}
	}
}

func jsonInt(n int) string { b, _ := json.Marshal(n); return string(b) }

func TestTheStartKeepsTheNewestSessionFiles(t *testing.T) {
	dir := t.TempDir()
	old := time.Now().Add(-time.Hour)
	for i, name := range []string{"a.jsonl", "b.jsonl", "c.jsonl", "d.jsonl", "e.jsonl", "notes.txt"} {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte("{}\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		mod := old.Add(time.Duration(i) * time.Minute)
		if name == "notes.txt" {
			mod = old.Add(-time.Hour)
		}
		if err := os.Chtimes(path, mod, mod); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := started(t, dir, on(t, "config.keep = 2\n")); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(dir)
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	if strings.Join(names, " ") != "d.jsonl e.jsonl notes.txt" {
		t.Fatalf("the folder holds %v, and wants the two newest session files and notes.txt", names)
	}
}

func TestAMissingFolderIsNoErrorAtStart(t *testing.T) {
	if _, err := started(t, filepath.Join(t.TempDir(), "none"), on(t, "")); err != nil {
		t.Fatal(err)
	}
}

func TestAValueBelowOneRefusesTheStart(t *testing.T) {
	for _, key := range []string{"keep", "max-bytes"} {
		_, err := started(t, t.TempDir(), on(t, "config."+key+" = 0\n"))
		if err == nil || !strings.Contains(err.Error(), "config "+key) {
			t.Errorf("%s = 0 starts with %v, and wants a refusal naming the key", key, err)
		}
	}
}

func TestAnInstanceSwitchedOffHearsNothing(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "sessions")
	ix, err := started(t, dir, on(t, "enabled = false\n"))
	if err != nil {
		t.Fatal(err)
	}
	if err := ix.Hear("E", []byte(`{"session_id": "s1"}`)); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("a switched-off instance left the folder (%v), and wants none", err)
	}
}

func TestTheFolderAndTheFileAreTheOwnersAlone(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows has no Unix modes")
	}
	dir := filepath.Join(t.TempDir(), "sessions")
	ix, err := started(t, dir, on(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	if err := ix.Hear("E", []byte(`{"session_id": "s1"}`)); err != nil {
		t.Fatal(err)
	}
	for path, want := range map[string]os.FileMode{dir: 0o700, filepath.Join(dir, "s1.jsonl"): 0o600} {
		fi, err := os.Stat(path)
		if err != nil {
			t.Fatal(err)
		}
		if fi.Mode().Perm() != want {
			t.Errorf("%s has mode %v, and wants %v", path, fi.Mode().Perm(), want)
		}
	}
}

func TestTheComponentDeclaresNoOutputVerbOrCommand(t *testing.T) {
	c := session.New(session.Options{}).Component
	if len(c.Outputs()) != 0 || len(c.Verbs()) != 0 || len(c.Commands()) != 0 {
		t.Fatalf("session declares outputs %v, verbs %v and commands %v, and wants none", c.Outputs(), c.Verbs(), c.Commands())
	}
}

// syncBuf is the core's log, written from its goroutines.
type syncBuf struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuf) Write(p []byte) (int, error) { s.mu.Lock(); defer s.mu.Unlock(); return s.b.Write(p) }
func (s *syncBuf) String() string              { s.mu.Lock(); defer s.mu.Unlock(); return s.b.String() }

// serve runs the real core over w, carrying the component over dir where
// dir is set, and posts payload as event twice; it answers the hook's
// answers and the core's log.
func serve(t *testing.T, w index.Wiring, dir, event, payload string) ([]host.HookAnswer, string) {
	t.Helper()
	var comps []*index.Component
	if dir != "" {
		comps = append(comps, session.New(session.Options{Dir: dir, Now: func() time.Time { return nine }}).Component)
	}
	log := &syncBuf{}
	c, err := host.Serve(host.Options{Root: t.TempDir(), Wiring: w, Components: comps, Log: log})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { c.Stop("the case ends"); <-c.Ended() }()
	s, _ := c.Standing()
	var answers []host.HookAnswer
	for i := 0; i < 2; i++ {
		a, err := host.Post(host.Wall{}, s.Root, event, []byte(payload), 10*time.Second)
		if err != nil {
			t.Fatal(err)
		}
		answers = append(answers, a)
	}
	return answers, log.String()
}

const toolUse = `{"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}`

func TestAHookPostThroughTheCoreWritesItsLine(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "sessions")
	serve(t, on(t, ""), dir, "PostToolUse", toolUse)
	got := lines(t, filepath.Join(dir, "s1.jsonl"))
	if len(got) != 2 || !strings.Contains(got[0], `"event":"PostToolUse","session":"s1","payload":{"session_id":"s1"`) {
		t.Fatalf("s1.jsonl holds %q, and wants the two posts' lines", got)
	}
}

func TestAFolderThatCannotBeMadeLeavesTheAnswerAndOneLogLine(t *testing.T) {
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	empty, err := index.ParseWiring(nil)
	if err != nil {
		t.Fatal(err)
	}
	want, _ := serve(t, empty, "", "PostToolUse", toolUse)
	got, log := serve(t, on(t, ""), filepath.Join(file, "sessions"), "PostToolUse", toolUse)
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("the hook answers %+v with the record failing, and wants %+v as without it", got[i], want[i])
		}
	}
	var failed []string
	for _, l := range strings.Split(log, "\n") {
		if strings.Contains(l, "instance session") {
			failed = append(failed, l)
		}
	}
	if len(failed) != 1 {
		t.Fatalf("the core's log holds %d lines of the record's failure, and wants exactly one:\n%s", len(failed), log)
	}
}
