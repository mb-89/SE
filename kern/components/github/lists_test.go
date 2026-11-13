package github_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/mb-89/kern/components/github"
	"github.com/mb-89/kern/index"
)

// lister is another component, which lists GitHub through the component's
// verbs alone: `list issues|pulls OWNER REPO STATE [LABEL...]` and
// `comments OWNER REPO N` show the numbers or ids they are answered.
var lister = func() *index.Component {
	issues := index.Request[github.ListRef, github.List]("issues", "Lists issues.")
	pulls := index.Request[github.ListRef, github.List]("pulls", "Lists pull requests.")
	comments := index.Request[github.Ref, github.Snapshot]("comments", "Reads comments.")
	ports := map[string]*index.RequestPort[github.ListRef, github.List]{"issues": issues, "pulls": pulls}
	ids := func(items []any, field string) string {
		out := []string{}
		for _, item := range items {
			out = append(out, fmt.Sprint(item.(map[string]any)[field]))
		}
		return strings.Join(out, " ")
	}
	return index.Declare("lister", "Lists GitHub through the github component.", issues, pulls, comments,
		index.Command(index.CommandDecl{
			Name: "list", Usage: "list KIND OWNER REPO STATE [LABEL...]", Summary: "List one repository.", Help: "Shows the numbers it lists.",
			Group: "Fixtures", Class: index.Batch,
		}, func(_ struct{}, args []string) (index.Result, error) {
			p := ports[args[0]]
			return index.Result{Requests: []index.Ask{p.Ask(github.ListRef{Owner: args[1], Repo: args[2], State: args[3], Labels: args[4:]})}, Then: func(a []any) (index.Result, error) {
				l := p.Answer(a[0])
				return index.Result{Text: fmt.Sprintf("[%s], read %s via %s", ids(l.Data, "number"), l.Read.Format(time.RFC3339), l.Via)}, nil
			}}, nil
		}),
		index.Command(index.CommandDecl{
			Name: "comments", Usage: "comments OWNER REPO N", Summary: "Read one thread.", Help: "Shows the comment ids it reads.",
			Group: "Fixtures", Class: index.Batch,
		}, func(_ struct{}, args []string) (index.Result, error) {
			var n int
			fmt.Sscanf(args[2], "%d", &n)
			return index.Result{Requests: []index.Ask{comments.Ask(github.Ref{Owner: args[0], Repo: args[1], Number: n})}, Then: func(a []any) (index.Result, error) {
				s := comments.Answer(a[0])
				return index.Result{Text: fmt.Sprintf("[%s], read %s via %s", ids(s.Data.([]any), "id"), s.Read.Format(time.RFC3339), s.Via)}, nil
			}}, nil
		}),
	)
}()

// listWiring is a checkout's wiring with the component and the lister.
func listWiring(t *testing.T, config string) index.Wiring {
	t.Helper()
	w, err := index.ParseWiring([]byte(fmt.Sprintf(`
[instances.github]
component = "github"
config = { %s }

[instances.lister]
component = "lister"

[wires]
"github.issue-lists" = "github/issue-lists/<key>"
"github.pull-lists" = "github/pull-lists/<key>"
"github.comments" = "github/comments/<key>"
"github.outbox" = "github/outbox/<key>"
"lister.issues" = "github.issue-list"
"lister.pulls" = "github.pull-list"
"lister.comments" = "github.comment-list"
`, config)))
	if err != nil {
		t.Fatal(err)
	}
	return w
}

func startedLists(t *testing.T, o github.Options, w index.Wiring) *index.Index {
	t.Helper()
	ix, err := index.Start(w, github.New(o).Component, lister)
	if err != nil {
		t.Fatal(err)
	}
	return ix
}

func readName[T any](t *testing.T, ix *index.Index, name string) T {
	t.Helper()
	v, err := ix.Read(name)
	if err != nil {
		t.Fatal(err)
	}
	if !v.Provided {
		t.Fatalf("%s reads its built-in value, and wants what was read", name)
	}
	return v.V.(T)
}

// The paged REST answers of the fake: two pages of open issues labelled
// work (the issues list holds a pull request, which the issue list drops),
// one page of closed pull requests and two pages of an issue's comments.
func pagedFake(t *testing.T) (*fakeGitHub, string) {
	f, srv := newFake(t)
	issues := "/repos/alice/demo/issues?labels=work&page=%d&per_page=100&state=open"
	f.bodies[fmt.Sprintf(issues, 1)] = `[{"number": 12}, {"number": 11, "pull_request": {"url": "x"}}]`
	f.bodies[fmt.Sprintf(issues, 2)] = `[{"number": 9}]`
	f.links[fmt.Sprintf(issues, 1)] = `<` + srv.URL + fmt.Sprintf(issues, 2) + `>; rel="next", <` + srv.URL + fmt.Sprintf(issues, 2) + `>; rel="last"`
	f.bodies["/repos/alice/demo/pulls?page=1&per_page=100&state=closed"] = `[{"number": 8}, {"number": 6}]`
	thread := "/repos/alice/demo/issues/7/comments?page=%d&per_page=100"
	f.bodies[fmt.Sprintf(thread, 1)] = `[{"id": 101}, {"id": 102}]`
	f.bodies[fmt.Sprintf(thread, 2)] = `[{"id": 103}]`
	f.links[fmt.Sprintf(thread, 1)] = `<` + srv.URL + fmt.Sprintf(thread, 2) + `>; rel="next"`
	return f, srv.URL
}

// The token backend lists through REST, every page, each page with its own
// ETag: the list name holds every item with its read time, and the refresh
// reads each page again and is answered 304 from what it holds.
func TestTheTokenBackendListsEveryPageWithETags(t *testing.T) {
	t.Parallel()
	f, api := pagedFake(t)
	clk := &clock{now: nine}
	var refresh func()
	ix := startedLists(t, github.Options{Now: clk.Now, Token: token(""), Cloud: notCloud, Every: func(_ time.Duration, fn func()) { refresh = fn }},
		listWiring(t, fmt.Sprintf(`api = %q`, api)))
	r, err := ix.Call("list", "issues", "Alice", "demo", "", "work")
	if err != nil || r.Text != "[12 9], read 2026-11-13T09:00:00Z via token" {
		t.Fatalf("list issues answers %q, %v, and wants both pages without the pull request", r.Text, err)
	}
	l := readName[github.List](t, ix, "github/issue-lists/alice.demo.open.work")
	if l.Repo != "alice/demo" || l.State != "open" || fmt.Sprint(l.Labels) != "[work]" || l.Read != nine || l.Via != github.Token {
		t.Fatalf("the list is %+v", l)
	}
	if r, err = ix.Call("list", "pulls", "alice", "demo", "closed"); err != nil || !strings.HasPrefix(r.Text, "[8 6]") {
		t.Fatalf("list pulls answers %q, %v", r.Text, err)
	}
	readName[github.List](t, ix, "github/pull-lists/alice.demo.closed")
	if r, err = ix.Call("comments", "alice", "demo", "7"); err != nil || !strings.HasPrefix(r.Text, "[101 102 103]") {
		t.Fatalf("comments answers %q, %v, and wants both pages", r.Text, err)
	}
	if s := readName[github.Snapshot](t, ix, "github/comments/alice.demo.7"); s.Number != 7 || len(s.Data.([]any)) != 3 {
		t.Fatalf("the comments snapshot is %+v", s)
	}
	_, before := f.log()
	clk.move(2 * time.Minute)
	refresh()
	asked, answered := f.log()
	if again := fmt.Sprint(answered[len(before):]); again != "[304 304 304 304 304]" {
		t.Fatalf("the refresh was answered %v, and wants every page of the three reads 304: asked %q", again, asked[len(before):])
	}
	for _, a := range asked[len(before):] {
		if !strings.Contains(a, ` "`) {
			t.Fatalf("the refresh asked %q without its ETag", a)
		}
	}
	if l := readName[github.List](t, ix, "github/issue-lists/alice.demo.open.work"); l.Read != nine.Add(2*time.Minute) || len(l.Data) != 2 {
		t.Fatalf("after the refresh the list is %+v", l)
	}
}

// A rate limit on a later page is sat out like any other, and the list
// goes on from that page.
func TestTheTokenBackendPacesAListsPages(t *testing.T) {
	t.Parallel()
	f, api := pagedFake(t)
	f.refuseAt["/repos/alice/demo/issues/7/comments?page=2&per_page=100"] = []func(http.ResponseWriter){func(w http.ResponseWriter) {
		w.Header().Set("Retry-After", "5")
		w.WriteHeader(http.StatusTooManyRequests)
	}}
	clk := &clock{now: nine}
	var slept []time.Duration
	ix := startedLists(t, github.Options{Now: clk.Now, Token: token(""), Cloud: notCloud, Every: func(time.Duration, func()) {},
		Sleep: func(d time.Duration) { slept = append(slept, d); clk.move(d) }}, listWiring(t, fmt.Sprintf(`api = %q`, api)))
	r, err := ix.Call("comments", "alice", "demo", "7")
	if err != nil || r.Text != "[101 102 103], read 2026-11-13T09:00:05Z via token" || fmt.Sprint(slept) != "[5s]" {
		t.Fatalf("comments answers %q, %v after sleeping %v, and wants every page after 5s", r.Text, err, slept)
	}
	if asked, _ := f.log(); len(asked) != 3 {
		t.Fatalf("GitHub was asked %q, and wants page 1, page 2 refused, page 2", asked)
	}
}

// A read that names what GitHub cannot list is refused before it goes out.
func TestAListReadIsChecked(t *testing.T) {
	t.Parallel()
	ix := startedLists(t, github.Options{Token: noToken}, listWiring(t, ``))
	for args, want := range map[string]string{
		"pulls alice demo open work": "lists pull requests by no label",
		"issues alice demo shut":     `state "shut" is none of open, closed and all`,
	} {
		if _, err := ix.Call("list", strings.Fields(args)...); err == nil || !strings.Contains(err.Error(), want) {
			t.Fatalf("list %s answers %v, and wants %q", args, err, want)
		}
	}
}

// issuesPage is a page as list_issues answers it.
func issuesPage(numbers []int, next string) string {
	items := []string{}
	for _, n := range numbers {
		items = append(items, fmt.Sprintf(`{"number": %d, "state": "OPEN", "labels": ["work"]}`, n))
	}
	return fmt.Sprintf(`{"issues": [%s], "pageInfo": {"hasNextPage": %t, "hasPreviousPage": false, "endCursor": %q}, "totalCount": 3}`,
		strings.Join(items, ", "), next != "", next)
}

// Through the relay a list goes out as the outbox step of its first page;
// list_issues answers a page with its cursor, so the step moves to the next
// page with after, and the last page lands every item at once and drops the step.
func TestTheRelayListsIssuesPageByPage(t *testing.T) {
	t.Parallel()
	clk := &clock{now: nine}
	ix := startedLists(t, github.Options{Now: clk.Now, Token: noToken}, listWiring(t, ``))
	_, err := ix.Call("list", "issues", "alice", "demo", "open", "work")
	if err == nil || !strings.Contains(err.Error(), `run the GitHub tool list_issues with {"labels":["work"],"owner":"alice","perPage":100,"repo":"demo","state":"OPEN"}; outbox step issue-list.alice.demo.open.work`) {
		t.Fatalf("the list answers %v, and wants it to name the first page's call", err)
	}
	first := map[string]any{"owner": "alice", "repo": "demo", "state": "OPEN", "labels": []string{"work"}, "perPage": 100}
	clk.move(time.Second)
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__list_issues", first, issuesPage([]int{12, 11}, "Y3Vyc29yOjI="))); err != nil {
		t.Fatal(err)
	}
	if v, _ := ix.Read("github/issue-lists/alice.demo.open.work"); v.Provided {
		t.Fatalf("a first page landed as the list: %+v", v.V)
	}
	step := readName[github.Step](t, ix, "github/outbox/issue-list.alice.demo.open.work")
	if step.Tool != "list_issues" || step.Input["after"] != "Y3Vyc29yOjI=" || step.Asked != nine.Add(time.Second) {
		t.Fatalf("the outbox holds %+v, and wants the next page asked with after", step)
	}
	_, err = ix.Call("list", "issues", "alice", "demo", "open", "work")
	if err == nil || !strings.Contains(err.Error(), `"after":"Y3Vyc29yOjI="`) {
		t.Fatalf("a list under way answers %v, and wants it to name the next page's call", err)
	}
	// A page nobody waits for counts for nothing.
	stray := map[string]any{"owner": "alice", "repo": "demo", "state": "OPEN", "labels": []string{"work"}, "after": "b3RoZXI="}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__list_issues", stray, issuesPage([]int{1}, ""))); err != nil {
		t.Fatal(err)
	}
	clk.move(time.Second)
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__list_issues", step.Input, issuesPage([]int{9}, ""))); err != nil {
		t.Fatal(err)
	}
	l := readName[github.List](t, ix, "github/issue-lists/alice.demo.open.work")
	if len(l.Data) != 3 || l.Read != nine.Add(2*time.Second) || l.Via != github.Relay || l.State != "open" {
		t.Fatalf("the list is %+v, and wants the three items of both pages, read at 09:00:02 via relay", l)
	}
	if v, _ := ix.Read("github/outbox/issue-list.alice.demo.open.work"); v.Provided {
		t.Fatalf("the answered step stands in the outbox: %+v", v.V)
	}
	r, err := ix.Call("list", "issues", "alice", "demo", "open", "work")
	if err != nil || r.Text != "[12 11 9], read 2026-11-13T09:00:02Z via relay" {
		t.Fatalf("the next list answers %q, %v, and wants the list", r.Text, err)
	}
}

// numbered is a page of n items as the bare-list tools answer it.
func numbered(from, n int, field string) string {
	items := []string{}
	for i := 0; i < n; i++ {
		items = append(items, fmt.Sprintf(`{%q: %d}`, field, from+i))
	}
	return "[" + strings.Join(items, ", ") + "]"
}

// list_pull_requests answers bare pages: a page as long as perPage has a
// next, which the step asks with page; a shorter one is the last. With
// relay-wait the list waits through every page.
func TestTheRelayListsPullsPageByPage(t *testing.T) {
	t.Parallel()
	ix := startedLists(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, listWiring(t, `relay-wait = "10s"`))
	go func() {
		pages := map[float64]string{1: numbered(1, 100, "number"), 2: numbered(101, 1, "number")}
		for len(pages) > 0 {
			if v, _ := ix.Read("github/outbox/pull-list.alice.demo.all"); v.Provided {
				in := v.V.(github.Step).Input
				page, _ := in["page"].(int)
				if page == 0 {
					page = 1
				}
				if body, ok := pages[float64(page)]; ok {
					delete(pages, float64(page))
					_ = ix.Hear(github.PostToolUse, toolUse("mcp__github__list_pull_requests", in, body))
				}
			}
			time.Sleep(time.Millisecond)
		}
	}()
	r, err := ix.Call("list", "pulls", "alice", "demo", "all")
	if err != nil || !strings.HasSuffix(r.Text, "100 101], read 2026-11-13T09:00:00Z via relay") {
		t.Fatalf("the waiting list answers %.80q, %v, and wants 101 pull requests", r.Text, err)
	}
}

// Comments are paged as list_pull_requests is, through issue_read; a pull
// request's comments read through pull_request_read land at the same key.
func TestTheRelayReadsCommentsPageByPage(t *testing.T) {
	t.Parallel()
	ix := startedLists(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, listWiring(t, ``))
	if _, err := ix.Call("comments", "alice", "demo", "7"); err == nil ||
		!strings.Contains(err.Error(), `issue_read with {"issue_number":7,"method":"get_comments","owner":"alice","perPage":100,"repo":"demo"}`) {
		t.Fatalf("comments answers %v, and wants the first page's call", err)
	}
	in := map[string]any{"method": "get_comments", "owner": "alice", "repo": "demo", "issue_number": 7, "perPage": 100}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_read", in, numbered(1, 100, "id"))); err != nil {
		t.Fatal(err)
	}
	step := readName[github.Step](t, ix, "github/outbox/comment-list.alice.demo.7")
	if step.Input["page"] != 2 {
		t.Fatalf("the outbox holds %+v, and wants page 2 asked", step)
	}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__issue_read", step.Input, `[]`)); err != nil {
		t.Fatal(err)
	}
	if s := readName[github.Snapshot](t, ix, "github/comments/alice.demo.7"); len(s.Data.([]any)) != 100 {
		t.Fatalf("the comments are %d, and want 100", len(s.Data.([]any)))
	}
	pull := map[string]any{"method": "get_comments", "owner": "alice", "repo": "demo", "pullNumber": 8}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__pull_request_read", pull, numbered(1, 2, "id"))); err != nil {
		t.Fatal(err)
	}
	if s := readName[github.Snapshot](t, ix, "github/comments/alice.demo.8"); len(s.Data.([]any)) != 2 {
		t.Fatalf("the pull request's comments are %+v", s)
	}
}

// A list answer nobody asked lands where it is the whole list; a first page
// with more behind it, a list narrowed beyond state and labels and an error
// answer land nothing.
func TestAnUnaskedListLandsOnlyWhole(t *testing.T) {
	t.Parallel()
	ix := startedLists(t, github.Options{Now: (&clock{now: nine}).Now, Token: noToken}, listWiring(t, ``))
	before := ix.Snapshot().Revision()
	for _, p := range [][]byte{
		toolUse("mcp__github__list_issues", map[string]any{"owner": "alice", "repo": "demo"}, issuesPage([]int{3}, "bW9yZQ==")),
		toolUse("mcp__github__list_issues", map[string]any{"owner": "alice", "repo": "demo", "fields": []string{"number"}}, issuesPage([]int{3}, "")),
		toolUse("mcp__github__list_pull_requests", map[string]any{"owner": "alice", "repo": "demo", "head": "alice:x"}, `[]`),
		toolUse("mcp__github__list_pull_requests", map[string]any{"owner": "alice", "repo": "demo"}, numbered(1, 30, "number")),
	} {
		if err := ix.Hear(github.PostToolUse, p); err != nil {
			t.Fatal(err)
		}
	}
	if err := ix.Hear(github.PostToolUse, []byte(`{"tool_name": "mcp__github__list_issues", "tool_input": {"owner": "alice", "repo": "demo"},
		"tool_response": {"content": [{"type": "text", "text": "Bad credentials"}], "isError": true}}`)); err == nil {
		t.Fatal("an error answer is heard without a word, and wants it named")
	}
	if rev := ix.Snapshot().Revision(); rev != before {
		t.Fatalf("the store moved from revision %d to %d", before, rev)
	}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__list_issues", map[string]any{"owner": "Alice", "repo": "Demo", "state": "CLOSED"}, issuesPage([]int{3, 2}, ""))); err != nil {
		t.Fatal(err)
	}
	if l := readName[github.List](t, ix, "github/issue-lists/alice.demo.closed"); len(l.Data) != 2 || l.Via != github.Relay {
		t.Fatalf("the unasked whole list is %+v", l)
	}
	if err := ix.Hear(github.PostToolUse, toolUse("mcp__github__list_pull_requests", map[string]any{"owner": "alice", "repo": "demo"}, numbered(1, 29, "number"))); err != nil {
		t.Fatal(err)
	}
	readName[github.List](t, ix, "github/pull-lists/alice.demo.open")
}

// A list's key names its state and its labels in order, each label in lower
// case with every character a key cannot hold written as a dash.
func TestAListsKey(t *testing.T) {
	t.Parallel()
	got := github.ListKey(github.ListRef{Owner: "Alice", Repo: "Demo", State: "open", Labels: []string{"work", "In Progress", "a:b"}})
	if want := "alice.demo.open.a-b.in-progress.work"; got != want {
		t.Fatalf("the key is %q, and wants %q", got, want)
	}
	if b, _ := json.Marshal(github.ListRef{Owner: "a", Repo: "b"}); string(b) != `{"owner":"a","repo":"b"}` {
		t.Fatalf("a list read marshals as %s", b)
	}
}
