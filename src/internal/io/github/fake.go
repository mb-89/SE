package github

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

// Fake is a GitHub that keeps its repositories in memory and answers from
// them as GitHub would: an issue it creates is listed, a comment it is sent is
// read back, a closed issue leaves the open list, a merged PR the open ones.
// It knows the routes SE uses: issues with their comments, labels,
// assignees, sub-issues and blocked-by links, branches (git refs: each
// repository starts with main, and a file written to a branch through
// contents is a new commit on it), pull requests with their merge and
// auto-merge, commit statuses, and who may write: the account it is logged in
// as administers every repository. Any other path it answers from what was
// seeded at that path, read-only.
//
// Seed fills it from recorded gh answers, each read for what it says about
// the repository rather than kept as an answer.
type Fake struct {
	// Proxy puts the fake behind a Claude Code cloud session's proxy: GraphQL
	// is refused, auto-merge is the REST route pulls/<n>/ccr/auto_merge, and
	// deleting a branch is refused.
	Proxy bool
	// NoAutoMerge is a repository that does not allow auto-merge.
	NoAutoMerge bool
	// Login is who the fake is logged in as: the author of what it writes.
	Login string

	mu     sync.Mutex
	clock  clock.Clock
	repos  map[string]*repo
	writes []string
	// later is what the repository comes to hold at a time, earliest first.
	later []timed
	// requests counts what gh would have asked GitHub; each passes delay on delayOn.
	requests int
	delay    time.Duration
	delayOn  clock.Clock
	// quota is GitHub's hourly limit on requests, content its limit on
	// creating content; rate is what the last answer said of the quota.
	quota   quota
	content content
	rate    Rate
}

// quota is a limit of requests a window, counted from the window's start.
type quota struct {
	limit  int
	window time.Duration
	start  time.Time
	used   int
}

// content is a limit of writes in any span of per, and when each was made.
type content struct {
	n     int
	per   time.Duration
	stamp []time.Time
}

// timed is recorded answers the repository holds from at on.
type timed struct {
	at      time.Time
	answers map[string]string
}

type obj = map[string]any

// repo is one repository's state.
type repo struct {
	name   string
	issues map[int]obj
	order  []int // issue numbers in the order they came
	// seen is every issue number something was seeded or written for.
	seen map[int]bool
	// deleted is every issue a person deleted: its number is never given again.
	deleted   map[int]bool
	comments  map[int][]obj
	subs      map[int][]int
	blockedBy map[int][]int
	// linked is when each blocked-by link, blocked and blocker, was written;
	// a seeded link has none.
	linked map[[2]int]time.Time
	// now is the fake's clock, which the dependency summary lags by.
	now  func() time.Time
	refs map[string]obj
	// commits counts the commits written, each a new sha.
	commits   int
	pulls     map[int]obj
	pullOrder []int
	// statuses are each commit's statuses, by its sha, newest first.
	statuses map[string][]obj
	docs     map[string][]byte
}

// NewFake answers an empty fake GitHub whose stamps are read from c.
func NewFake(c clock.Clock) *Fake {
	return &Fake{Login: "se-fake", clock: c, repos: map[string]*repo{}, quota: quota{limit: Quota, window: time.Hour}}
}

// Quota is the fake's built-in limit of requests an hour: the owner's
// token's, which the whole fleet shares.
const Quota = 15000

// Quota limits the fake to limit requests a window, as GitHub limits a token
// to its requests an hour: the window opens at the first request, and a
// request past the limit is refused with 403 and the quota's headers until
// the window resets on the fake's clock.
func (f *Fake) Quota(limit int, window time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.quota = quota{limit: limit, window: window}
}

// ContentLimit limits the fake to n writes in any span of per, as GitHub's
// secondary limit does content creation: a write past it is refused with
// 403, a secondary rate limit, and a retry-after until the oldest leaves the
// span.
func (f *Fake) ContentLimit(n int, per time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.content = content{n: n, per: per}
}

// Rate answers the quota as the fake's last answer gave it.
func (f *Fake) Rate() Rate {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.rate
}

// admit counts a request against the quota, and a write against the
// content limit, with f.mu held; it refuses one past either as GitHub does.
func (f *Fake) admit(write bool) error {
	now := f.clock.Now()
	q := &f.quota
	if q.limit > 0 {
		if q.start.IsZero() || !now.Before(q.start.Add(q.window)) {
			q.start, q.used = now, 0
		}
		f.rate = Rate{Known: true, Limit: q.limit, Remaining: max(q.limit-q.used-1, 0), Reset: q.start.Add(q.window)}
		if q.used >= q.limit {
			f.rate.Remaining = 0
			return &Error{Status: 403, Message: "gh: API rate limit exceeded for user ID 1.", Rate: f.rate}
		}
		q.used++
	}
	if c := &f.content; write && c.n > 0 {
		kept := c.stamp[:0]
		for _, at := range c.stamp {
			if now.Sub(at) < c.per {
				kept = append(kept, at)
			}
		}
		c.stamp = kept
		if len(c.stamp) >= c.n {
			r := f.rate
			r.RetryAfter = max(c.stamp[0].Add(c.per).Sub(now).Round(time.Second), time.Second)
			return &Error{Status: 403, Message: "gh: You have exceeded a secondary rate limit. Please wait a few minutes before you try again.", Rate: r}
		}
		c.stamp = append(c.stamp, now)
	}
	return nil
}

// used counts n more requests against the quota, with f.mu held: the pages
// of a List past its first.
func (f *Fake) used(n int) {
	if f.quota.limit > 0 && n > 0 {
		f.quota.used += n
		f.rate.Remaining = max(f.rate.Remaining-n, 0)
	}
}

// Delay makes each request the fake takes pass d on c, as a request to
// GitHub takes time: the battery runs the interactive commands so, against
// their budgets (spec/budgets.yaml).
func (f *Fake) Delay(c clock.Clock, d time.Duration) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.delayOn, f.delay = c, d
}

// Requests answers how many requests the fake took, as gh would make them:
// one for each Get, Send and GraphQL, and one for each page of a List.
func (f *Fake) Requests() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.requests
}

// spend counts n requests and passes their delay, with the fake unlocked.
func (f *Fake) spend(n int) {
	f.mu.Lock()
	f.requests += n
	c, d := f.delayOn, f.delay
	f.mu.Unlock()
	if c != nil && d > 0 {
		c.Sleep(time.Duration(n) * d)
	}
}

// Writes lists every write the fake took, oldest first, as "METHOD path"
// ("POST graphql" for a GraphQL call), refused ones included.
func (f *Fake) Writes() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.writes...)
}

func notFound() error { return &Error{Status: 404, Message: "gh: Not Found"} }

func refuse(status int, msg string) error { return &Error{Status: status, Message: "gh: " + msg} }

// route splits a path into its repository, the words after it, and its query.
func route(path string) (r string, words []string, q url.Values, err error) {
	u, err := url.Parse(path)
	if err != nil {
		return "", nil, nil, refuse(400, "bad path "+path)
	}
	w := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(w) < 3 || w[0] != "repos" {
		return "", nil, nil, notFound()
	}
	return w[1] + "/" + w[2], w[3:], u.Query(), nil
}

func (f *Fake) repo(name string) *repo {
	r, ok := f.repos[name]
	if !ok {
		r = &repo{
			name: name, issues: map[int]obj{}, seen: map[int]bool{}, deleted: map[int]bool{}, comments: map[int][]obj{},
			subs: map[int][]int{}, blockedBy: map[int][]int{}, linked: map[[2]int]time.Time{}, now: f.clock.Now, refs: map[string]obj{}, pulls: map[int]obj{}, statuses: map[string][]obj{}, docs: map[string][]byte{},
		}
		// A repository has its default branch from the start, as GitHub's do.
		r.refs[mainRef] = r.ref(mainRef, r.commit())
		f.repos[name] = r
	}
	return r
}

// mainRef is the default branch every fake repository starts with.
const mainRef = "refs/heads/main"

// commit answers the sha of a new commit in the repository.
func (r *repo) commit() string {
	r.commits++
	return fmt.Sprintf("%040x", r.commits)
}

// ref is a git ref as GitHub answers it, pointing at sha.
func (r *repo) ref(name, sha string) obj {
	return obj{"ref": name, "object": obj{"sha": sha, "type": "commit"}}
}

func (f *Fake) now() string { return f.clock.Now().UTC().Format(time.RFC3339) }

// Get answers the value at path.
func (f *Fake) Get(path string) ([]byte, error) {
	defer f.spend(1)
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.admit(false); err != nil {
		return nil, err
	}
	f.catchUp()
	v, err := f.read(path)
	if err != nil {
		return nil, err
	}
	return encode(v)
}

// List answers the list at path, whole, as the pages gh would ask for.
func (f *Fake) List(path string) ([]byte, error) {
	pages := 1
	defer func() { f.spend(pages) }()
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.admit(false); err != nil {
		return nil, err
	}
	defer func() { f.used(pages - 1) }()
	f.catchUp()
	v, err := f.read(path)
	if err != nil {
		return nil, err
	}
	if raw, ok := v.(json.RawMessage); ok {
		var list []json.RawMessage
		if json.Unmarshal(raw, &list) != nil {
			return nil, fmt.Errorf("gh api --paginate %s: not a list", path)
		}
		pages = len(list)/pageSize(path) + 1
		return raw, nil
	}
	list, ok := v.([]any)
	if !ok {
		return nil, fmt.Errorf("gh api --paginate %s: not a list", path)
	}
	pages = len(list)/pageSize(path) + 1
	return encode(v)
}

// encode writes v as GitHub does, leaving <, > and & as they are.
func encode(v any) ([]byte, error) {
	if raw, ok := v.(json.RawMessage); ok {
		return raw, nil
	}
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(b.Bytes(), "\n"), nil
}

// read answers the value at path; a list asked for by page answers that
// page alone, per_page items to a page (30 where it is not said).
func (f *Fake) read(path string) (any, error) {
	v, err := f.whole(path)
	if err != nil {
		return nil, err
	}
	u, _ := url.Parse(path)
	list, ok := v.([]any)
	if !ok || u == nil || u.Query().Get("page") == "" {
		return v, nil
	}
	page, size := num(u.Query().Get("page")), num(u.Query().Get("per_page"))
	if size == 0 {
		size = 30
	}
	from, to := min((page-1)*size, len(list)), min(page*size, len(list))
	if page < 1 {
		from, to = 0, 0
	}
	return list[from:to], nil
}

func (f *Fake) whole(path string) (any, error) {
	name, w, q, err := route(path)
	if err != nil {
		return nil, err
	}
	r := f.repo(name)
	switch {
	case match(w, "issues"):
		return r.listIssues(q), nil
	case match(w, "issues", "#"):
		return r.issue(num(w[1]))
	case match(w, "issues", "comments"):
		return r.allComments(q.Get("since")), nil
	case match(w, "issues", "#", "comments"):
		n := num(w[1])
		if !r.exists(n) {
			return nil, notFound()
		}
		out := []any{}
		for _, c := range r.comments[n] {
			out = append(out, c)
		}
		return out, nil
	case match(w, "issues", "#", "labels"):
		i, err := r.issue(num(w[1]))
		if err != nil {
			return nil, err
		}
		return i.(obj)["labels"], nil
	case match(w, "issues", "#", "sub_issues"):
		return r.issuesOf(num(w[1]), r.subs)
	case match(w, "issues", "#", "parent"):
		n := num(w[1])
		for _, p := range r.order {
			if contains(r.subs[p], n) {
				return r.issue(p)
			}
		}
		return nil, notFound()
	case match(w, "issues", "#", "dependencies", "blocked_by"):
		return r.issuesOf(num(w[1]), r.blockedBy)
	case match(w, "issues", "#", "dependencies", "blocking"):
		n := num(w[1])
		if !r.exists(n) {
			return nil, notFound()
		}
		out := []any{}
		for _, m := range r.order {
			if contains(r.blockedBy[m], n) {
				i, _ := r.issue(m)
				out = append(out, i)
			}
		}
		return out, nil
	case len(w) > 2 && w[0] == "git" && w[1] == "matching-refs":
		prefix := "refs/" + strings.Join(w[2:], "/")
		var names []string
		for ref := range r.refs {
			if strings.HasPrefix(ref, prefix) {
				names = append(names, ref)
			}
		}
		sort.Strings(names)
		out := []any{}
		for _, ref := range names {
			out = append(out, r.refs[ref])
		}
		return out, nil
	case match(w, "activity") && q.Get("ref") == "" && r.docs[path] == nil:
		return r.activity(), nil
	case match(w, "issues", "events") && r.docs[path] == nil:
		return r.events(), nil
	case match(w, "pulls"):
		return r.listPulls(q), nil
	case match(w, "pulls", "#"):
		p, ok := r.pulls[num(w[1])]
		if !ok {
			return nil, notFound()
		}
		return p, nil
	case len(w) == 3 && w[0] == "commits" && w[2] == "statuses" && len(r.statuses[w[1]]) > 0:
		out := []any{}
		for _, st := range r.statuses[w[1]] {
			out = append(out, st)
		}
		return out, nil
	}
	if doc, ok := r.docs[path]; ok {
		return json.RawMessage(doc), nil
	}
	switch {
	case len(w) == 3 && w[0] == "commits" && w[2] == "statuses":
		return []any{}, nil
	case len(w) == 3 && w[0] == "collaborators" && w[1] == f.Login && w[2] == "permission":
		return obj{"permission": "admin", "user": obj{"login": f.Login}}, nil
	}
	return nil, notFound()
}

// match says whether the path's words are these, # standing for a number.
func match(w []string, want ...string) bool {
	if len(w) != len(want) {
		return false
	}
	for k := range w {
		if want[k] == "#" {
			if n, err := strconv.Atoi(w[k]); err != nil || n <= 0 {
				return false
			}
		} else if w[k] != want[k] {
			return false
		}
	}
	return true
}

func num(s string) int { n, _ := strconv.Atoi(s); return n }

func contains(ns []int, n int) bool {
	for _, m := range ns {
		if m == n {
			return true
		}
	}
	return false
}

func (r *repo) exists(n int) bool {
	_, pull := r.pulls[n]
	return r.seen[n] || pull
}

// issue renders issue n as GitHub does; a pull request is an issue too.
func (r *repo) issue(n int) (any, error) {
	if p, ok := r.pulls[n]; ok {
		return obj{
			"number": n, "title": p["title"], "body": p["body"], "state": p["state"], "html_url": p["html_url"],
			"pull_request": obj{"url": fmt.Sprintf("https://api.github.com/repos/%s/pulls/%d", r.name, n)},
		}, nil
	}
	if r.deleted[n] {
		return nil, refuse(410, "This issue was deleted")
	}
	i, ok := r.issues[n]
	if !ok {
		return nil, notFound()
	}
	out := obj{}
	for k, v := range i {
		out[k] = v
	}
	if subs, ok := r.subs[n]; ok {
		done := 0
		for _, s := range subs {
			if r.issues[s]["state"] == "closed" {
				done++
			}
		}
		pct := 0
		if len(subs) > 0 {
			pct = done * 100 / len(subs)
		}
		out["sub_issues_summary"] = obj{"total": len(subs), "completed": done, "percent_completed": pct}
	}
	out["issue_dependencies_summary"] = r.dependencies(n)
	return out, nil
}

// SummaryLag is how long after a blocked-by link is written GitHub's
// issue_dependencies_summary still leaves it out, as the real one can right
// after the write. The links themselves never lag.
const SummaryLag = time.Minute

// dependencies is issue n's issue_dependencies_summary: its blockers and the
// issues it blocks, all and the open ones, leaving out a link written less
// than SummaryLag ago.
func (r *repo) dependencies(n int) obj {
	counted := func(blocked, blocker int) bool {
		at, ok := r.linked[[2]int{blocked, blocker}]
		return !ok || !r.now().Before(at.Add(SummaryLag))
	}
	open := func(m int) bool { st, _ := r.issues[m]["state"].(string); return st != "closed" }
	var blockedBy, totalBlockedBy, blocking, totalBlocking int
	for _, m := range r.blockedBy[n] {
		if counted(n, m) {
			totalBlockedBy++
			if open(m) {
				blockedBy++
			}
		}
	}
	for m, blockers := range r.blockedBy {
		if contains(blockers, n) && counted(m, n) {
			totalBlocking++
			if open(m) {
				blocking++
			}
		}
	}
	return obj{"blocked_by": blockedBy, "total_blocked_by": totalBlockedBy, "blocking": blocking, "total_blocking": totalBlocking}
}

// allComments is every comment on the repository's issues updated since
// since (RFC 3339; empty, all), oldest first, each naming its issue.
func (r *repo) allComments(since string) []any {
	var all []obj
	for n, cs := range r.comments {
		for _, c := range cs {
			at, _ := c["updated_at"].(string)
			if at == "" {
				at, _ = c["created_at"].(string)
			}
			if since != "" && at != "" && at < since {
				continue
			}
			out := obj{}
			for k, v := range c {
				out[k] = v
			}
			if _, ok := out["issue_url"]; !ok {
				out["issue_url"] = fmt.Sprintf("https://api.github.com/repos/%s/issues/%d", r.name, n)
			}
			all = append(all, out)
		}
	}
	sort.SliceStable(all, func(i, j int) bool {
		a, _ := all[i]["created_at"].(string)
		b, _ := all[j]["created_at"].(string)
		if a != b {
			return a < b
		}
		return idOf(all[i]) < idOf(all[j])
	})
	out := []any{}
	for _, c := range all {
		out = append(out, c)
	}
	return out
}

// activity is the repository's activity, newest first, as GitHub lists it
// for no one ref: every activity seeded for a ref of its own, each naming its
// ref, once.
func (r *repo) activity() []any {
	prefix := "repos/" + r.name + "/activity?"
	seen := map[string]bool{}
	var all []obj
	for path, doc := range r.docs {
		u, err := url.Parse(path)
		if !strings.HasPrefix(path, prefix) || err != nil || u.Query().Get("ref") == "" {
			continue
		}
		var list []obj
		if json.Unmarshal(doc, &list) != nil {
			continue
		}
		for _, a := range list {
			if _, ok := a["ref"]; !ok {
				a["ref"] = u.Query().Get("ref")
			}
			key := fmt.Sprint(a["ref"], a["timestamp"], a["activity_type"])
			if !seen[key] {
				seen[key] = true
				all = append(all, a)
			}
		}
	}
	at := func(a obj) string { s, _ := a["timestamp"].(string); return s }
	sort.SliceStable(all, func(i, j int) bool {
		if at(all[i]) != at(all[j]) {
			return at(all[i]) > at(all[j])
		}
		return fmt.Sprint(all[i]["ref"]) < fmt.Sprint(all[j]["ref"])
	})
	out := []any{}
	for _, a := range all {
		out = append(out, a)
	}
	return out
}

// events is the repository's issue events, newest first, as GitHub lists
// them: the fake keeps one for each blocked-by link written, on the issue it
// blocks; a seeded link has none.
func (r *repo) events() []any {
	type link struct {
		blocked int
		at      time.Time
	}
	var all []link
	for k, at := range r.linked {
		all = append(all, link{k[0], at})
	}
	sort.SliceStable(all, func(i, j int) bool {
		if !all[i].at.Equal(all[j].at) {
			return all[i].at.After(all[j].at)
		}
		return all[i].blocked < all[j].blocked
	})
	out := []any{}
	for k, l := range all {
		out = append(out, obj{
			"id": len(all) - k, "event": "blocked_by_added", "created_at": l.at.UTC().Format(time.RFC3339),
			"issue": obj{"number": l.blocked},
		})
	}
	return out
}

func (r *repo) issuesOf(n int, links map[int][]int) (any, error) {
	if !r.exists(n) {
		return nil, notFound()
	}
	out := []any{}
	for _, m := range links[n] {
		if i, err := r.issue(m); err == nil {
			out = append(out, i)
		}
	}
	return out, nil
}

func labelsOf(i obj) []string {
	var out []string
	ls, _ := i["labels"].([]any)
	for _, l := range ls {
		switch l := l.(type) {
		case string:
			out = append(out, l)
		case obj:
			if name, ok := l["name"].(string); ok {
				out = append(out, name)
			}
		}
	}
	return out
}

func (r *repo) listIssues(q url.Values) []any {
	state := q.Get("state")
	if state == "" {
		state = "open"
	}
	var want []string
	if l := q.Get("labels"); l != "" {
		want = strings.Split(l, ",")
	}
	since := q.Get("since")
	out := []any{}
	for _, n := range r.order {
		i := r.issues[n]
		if st, _ := i["state"].(string); state != "all" && st != state {
			continue
		}
		have := labelsOf(i)
		ok := true
		for _, l := range want {
			ok = ok && containsString(have, l)
		}
		if at, _ := i["updated_at"].(string); since != "" && at != "" && at < since {
			ok = false
		}
		if ok {
			v, _ := r.issue(n)
			out = append(out, v)
		}
	}
	// sort=updated lists the issues updated last first, as GitHub's
	// direction=desc does; any other order is the fake's own.
	if q.Get("sort") == "updated" {
		at := func(v any) string { s, _ := v.(obj)["updated_at"].(string); return s }
		desc := q.Get("direction") != "asc"
		sort.SliceStable(out, func(a, b int) bool {
			if desc {
				return at(out[a]) > at(out[b])
			}
			return at(out[a]) < at(out[b])
		})
	}
	return out
}

func containsString(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}

func refOf(p obj, side string) string {
	s, _ := p[side].(obj)
	ref, _ := s["ref"].(string)
	return ref
}

func (r *repo) listPulls(q url.Values) []any {
	state := q.Get("state")
	if state == "" {
		state = "open"
	}
	out := []any{}
	for _, n := range r.pullOrder {
		p := r.pulls[n]
		if st, _ := p["state"].(string); state != "all" && st != state {
			continue
		}
		if b := q.Get("base"); b != "" && refOf(p, "base") != b {
			continue
		}
		if h := q.Get("head"); h != "" {
			_, branch, _ := strings.Cut(h, ":")
			if refOf(p, "head") != branch {
				continue
			}
		}
		out = append(out, p)
	}
	return out
}

// Send takes a write and changes the repository as GitHub would.
func (f *Fake) Send(method, path string, fields ...Field) ([]byte, error) {
	defer f.spend(1)
	f.mu.Lock()
	defer f.mu.Unlock()
	f.writes = append(f.writes, method+" "+path)
	if err := f.admit(true); err != nil {
		return nil, err
	}
	f.catchUp()
	v, err := f.write(method, path, values(fields))
	if err != nil {
		return nil, err
	}
	if v == nil {
		return nil, nil
	}
	return encode(v)
}

// values reads fields as GitHub does: a name ending in [] adds to an array,
// and a typed field is a number.
func values(fields []Field) map[string]any {
	out := map[string]any{}
	for _, fl := range fields {
		var v any = fl.Value
		if fl.Typed {
			if n, err := strconv.ParseInt(fl.Value, 10, 64); err == nil {
				v = n
			}
		}
		if name, ok := strings.CutSuffix(fl.Name, "[]"); ok {
			list, _ := out[name].([]string)
			out[name] = append(list, fl.Value)
			continue
		}
		out[fl.Name] = v
	}
	return out
}

func str(v map[string]any, k string) (string, bool) {
	s, ok := v[k].(string)
	return s, ok
}

func (f *Fake) write(method, path string, v map[string]any) (any, error) {
	name, w, _, err := route(path)
	if err != nil {
		return nil, err
	}
	r := f.repo(name)
	switch {
	case method == "POST" && match(w, "issues"):
		return f.createIssue(r, v)
	case method == "PATCH" && match(w, "issues", "#"):
		return f.editIssue(r, num(w[1]), v)
	case method == "POST" && match(w, "issues", "#", "comments"):
		return f.comment(r, num(w[1]), v)
	case method == "PATCH" && match(w, "issues", "comments", "#"):
		c, err := r.findComment(int64(num(w[2])))
		if err != nil {
			return nil, err
		}
		if body, ok := str(v, "body"); ok {
			c["body"], c["updated_at"] = body, f.now()
		}
		return c, nil
	case method == "DELETE" && match(w, "issues", "comments", "#"):
		id := int64(num(w[2]))
		if _, err := r.findComment(id); err != nil {
			return nil, err
		}
		for n, cs := range r.comments {
			kept := cs[:0:0]
			for _, c := range cs {
				if idOf(c) != id {
					kept = append(kept, c)
				}
			}
			r.comments[n] = kept
		}
		return nil, nil
	case method == "POST" && match(w, "issues", "#", "labels"):
		i, ok := r.issues[num(w[1])]
		if !ok {
			return nil, notFound()
		}
		add, _ := v["labels"].([]string)
		for _, l := range add {
			if !containsString(labelsOf(i), l) {
				i["labels"] = append(asList(i["labels"]), obj{"name": l})
			}
		}
		i["updated_at"] = f.now()
		return i["labels"], nil
	case method == "DELETE" && len(w) == 4 && match(w[:3], "issues", "#", "labels"):
		i, ok := r.issues[num(w[1])]
		if !ok || !containsString(labelsOf(i), w[3]) {
			return nil, refuse(404, "Label does not exist")
		}
		kept := []any{}
		for _, l := range asList(i["labels"]) {
			if lo, ok := l.(obj); !ok || lo["name"] != w[3] {
				kept = append(kept, l)
			}
		}
		i["labels"], i["updated_at"] = kept, f.now()
		return kept, nil
	case method == "POST" && match(w, "issues", "#", "assignees"):
		i, ok := r.issues[num(w[1])]
		if !ok {
			return nil, notFound()
		}
		add, _ := v["assignees"].([]string)
		for _, a := range add {
			i["assignees"] = append(asList(i["assignees"]), obj{"login": a})
		}
		i["updated_at"] = f.now()
		return r.issue(num(w[1]))
	case method == "POST" && match(w, "issues", "#", "sub_issues"):
		return f.link(r, num(w[1]), v, "sub_issue_id", r.subs)
	case method == "POST" && match(w, "issues", "#", "dependencies", "blocked_by"):
		return f.link(r, num(w[1]), v, "issue_id", r.blockedBy)
	case method == "POST" && match(w, "git", "refs"):
		ref, _ := str(v, "ref")
		sha, _ := str(v, "sha")
		if !strings.HasPrefix(ref, "refs/") || strings.Count(ref, "/") < 2 || sha == "" {
			return nil, refuse(422, "Validation Failed: a ref takes a fully qualified name and a sha")
		}
		if _, ok := r.refs[ref]; ok {
			return nil, refuse(422, "Reference already exists")
		}
		r.refs[ref] = r.ref(ref, sha)
		return r.refs[ref], nil
	case method == "PUT" && len(w) > 1 && w[0] == "contents":
		// A file written to a branch is a new commit on it.
		branch, _ := str(v, "branch")
		if branch == "" {
			branch = strings.TrimPrefix(mainRef, "refs/heads/")
		}
		if msg, _ := str(v, "message"); msg == "" {
			return nil, refuse(422, "Validation Failed: a commit takes a message")
		}
		ref, ok := r.refs["refs/heads/"+branch]
		if !ok {
			return nil, refuse(404, "Branch "+branch+" not found")
		}
		sha := r.commit()
		ref["object"] = obj{"sha": sha, "type": "commit"}
		return obj{"content": obj{"path": strings.Join(w[1:], "/")}, "commit": obj{"sha": sha}}, nil
	case method == "DELETE" && len(w) > 3 && w[0] == "git" && w[1] == "refs":
		if f.Proxy {
			return nil, refuse(403, "Write access to this GitHub API path is not permitted through this proxy.")
		}
		ref := "refs/" + strings.Join(w[2:], "/")
		if _, ok := r.refs[ref]; !ok {
			return nil, refuse(422, "Reference does not exist")
		}
		delete(r.refs, ref)
		return nil, nil
	case method == "POST" && match(w, "pulls"):
		return f.openPull(r, v)
	case method == "PATCH" && match(w, "pulls", "#"):
		p, ok := r.pulls[num(w[1])]
		if !ok {
			return nil, notFound()
		}
		for _, k := range []string{"title", "body", "state"} {
			if s, ok := str(v, k); ok {
				p[k] = s
			}
		}
		p["updated_at"] = f.now()
		return p, nil
	case method == "PUT" && match(w, "pulls", "#", "merge"):
		p, ok := r.pulls[num(w[1])]
		if !ok {
			return nil, notFound()
		}
		if p["state"] != "open" {
			return nil, refuse(405, "Pull Request is not mergeable")
		}
		at := f.now()
		p["state"], p["merged"], p["merged_at"], p["closed_at"] = "closed", true, at, at
		return obj{"merged": true, "message": "Pull Request successfully merged"}, nil
	case method == "POST" && len(w) == 2 && w[0] == "statuses":
		state, _ := str(v, "state")
		if !containsString([]string{"error", "failure", "pending", "success"}, state) {
			return nil, refuse(422, "Validation Failed: state is not included in the list")
		}
		st := obj{"id": f.nextID(), "state": state, "creator": obj{"login": f.Login}, "created_at": f.now(), "updated_at": f.now()}
		for _, k := range []string{"context", "description", "target_url"} {
			st[k], _ = str(v, k)
		}
		if st["context"] == "" {
			st["context"] = "default"
		}
		r.statuses[w[1]] = append([]obj{st}, r.statuses[w[1]]...)
		return st, nil
	case method == "PUT" && f.Proxy && match(w, "pulls", "#", "ccr", "auto_merge"):
		p, ok := r.pulls[num(w[1])]
		if !ok {
			return nil, notFound()
		}
		if err := f.enableAutoMerge(p); err != nil {
			return nil, err
		}
		return obj{"enabled": true, "merge_method": "squash"}, nil
	}
	return nil, notFound()
}

func asList(v any) []any { l, _ := v.([]any); return l }

func idOf(o obj) int64 {
	switch id := o["id"].(type) {
	case json.Number:
		n, _ := id.Int64()
		return n
	case int64:
		return id
	case int:
		return int64(id)
	case float64:
		return int64(id)
	}
	return 0
}

func numberOf(o obj) int { return int(idOfKey(o, "number")) }

func idOfKey(o obj, k string) int64 { return idOf(obj{"id": o[k]}) }

func (r *repo) findComment(id int64) (obj, error) {
	for _, cs := range r.comments {
		for _, c := range cs {
			if idOf(c) == id {
				return c, nil
			}
		}
	}
	return nil, notFound()
}

// nextNumber is the number GitHub gives the next issue or pull request.
func (r *repo) nextNumber() int {
	top := 0
	for n := range r.seen {
		top = max(top, n)
	}
	for n := range r.pulls {
		top = max(top, n)
	}
	for n := range r.deleted {
		top = max(top, n)
	}
	return top + 1
}

// nextID is an id above every id the repository holds.
func (f *Fake) nextID() int64 {
	var top int64
	for _, r := range f.repos {
		for _, i := range r.issues {
			top = max(top, idOf(i))
		}
		for _, cs := range r.comments {
			for _, c := range cs {
				top = max(top, idOf(c))
			}
		}
		for _, p := range r.pulls {
			top = max(top, idOf(p))
		}
		for _, sts := range r.statuses {
			for _, st := range sts {
				top = max(top, idOf(st))
			}
		}
	}
	return top + 1
}

func (f *Fake) createIssue(r *repo, v map[string]any) (any, error) {
	title, _ := str(v, "title")
	if strings.TrimSpace(title) == "" {
		return nil, refuse(422, "Validation Failed: title is missing")
	}
	n := r.nextNumber()
	body, _ := str(v, "body")
	labels := []any{}
	ls, _ := v["labels"].([]string)
	for _, l := range ls {
		labels = append(labels, obj{"name": l})
	}
	assignees := []any{}
	as, _ := v["assignees"].([]string)
	for _, a := range as {
		assignees = append(assignees, obj{"login": a})
	}
	at := f.now()
	r.put(obj{
		"id": f.nextID(), "number": n, "title": title, "body": body, "state": "open", "state_reason": nil,
		"labels": labels, "assignees": assignees, "user": obj{"login": f.Login},
		"html_url":       fmt.Sprintf("https://github.com/%s/issues/%d", r.name, n),
		"repository_url": "https://api.github.com/repos/" + r.name,
		"created_at":     at, "updated_at": at, "closed_at": nil,
	})
	return r.issue(n)
}

func (f *Fake) editIssue(r *repo, n int, v map[string]any) (any, error) {
	i, ok := r.issues[n]
	if !ok {
		if _, pull := r.pulls[n]; pull {
			return nil, refuse(422, "an issue edit of a pull request")
		}
		return nil, notFound()
	}
	for _, k := range []string{"title", "body"} {
		if s, ok := str(v, k); ok {
			i[k] = s
		}
	}
	if st, ok := str(v, "state"); ok {
		if st != "open" && st != "closed" {
			return nil, refuse(422, "Validation Failed: state is open or closed")
		}
		if st == "closed" && i["state"] != "closed" {
			i["closed_at"] = f.now()
		}
		if st == "open" {
			i["closed_at"], i["state_reason"] = nil, "reopened"
		}
		i["state"] = st
	}
	if reason, ok := str(v, "state_reason"); ok {
		i["state_reason"] = reason
	}
	i["updated_at"] = f.now()
	return r.issue(n)
}

func (f *Fake) comment(r *repo, n int, v map[string]any) (any, error) {
	if _, ok := r.issues[n]; !ok {
		if _, pull := r.pulls[n]; !pull {
			return nil, notFound()
		}
	}
	body, _ := str(v, "body")
	if body == "" {
		return nil, refuse(422, "Validation Failed: body is missing")
	}
	id, at := f.nextID(), f.now()
	c := obj{
		"id": id, "body": body, "user": obj{"login": f.Login}, "created_at": at, "updated_at": at,
		"html_url": fmt.Sprintf("https://github.com/%s/issues/%d#issuecomment-%d", r.name, n, id),
	}
	r.comments[n] = append(r.comments[n], c)
	if i, ok := r.issues[n]; ok {
		i["updated_at"] = at
	}
	return c, nil
}

// link adds the issue whose id is v[key] to n's links: a sub-issue, which has
// one parent, or a blocker.
func (f *Fake) link(r *repo, n int, v map[string]any, key string, links map[int][]int) (any, error) {
	if _, ok := r.issues[n]; !ok {
		return nil, notFound()
	}
	id, _ := v[key].(int64)
	other := 0
	for m, i := range r.issues {
		if idOf(i) == id {
			other = m
		}
	}
	if other == 0 {
		return nil, refuse(404, "no issue has id "+strconv.FormatInt(id, 10))
	}
	if other == n {
		return nil, refuse(422, "an issue cannot link to itself")
	}
	if key == "sub_issue_id" {
		for p, subs := range r.subs {
			if p != n && contains(subs, other) {
				return nil, refuse(422, "Validation Failed: the sub-issue already has a parent")
			}
		}
	}
	if !contains(links[n], other) {
		links[n] = append(links[n], other)
		if key == "issue_id" {
			r.linked[[2]int{n, other}] = f.clock.Now()
		}
	}
	r.issues[n]["updated_at"] = f.now()
	return r.issue(n)
}

func (f *Fake) openPull(r *repo, v map[string]any) (any, error) {
	title, _ := str(v, "title")
	head, _ := str(v, "head")
	base, _ := str(v, "base")
	if title == "" || head == "" || base == "" {
		return nil, refuse(422, "Validation Failed: a pull request takes a title, a head and a base")
	}
	for _, p := range r.pulls {
		if p["state"] == "open" && refOf(p, "head") == head && refOf(p, "base") == base {
			return nil, refuse(422, "Validation Failed: A pull request already exists for "+head)
		}
	}
	n := r.nextNumber()
	body, _ := str(v, "body")
	at := f.now()
	p := obj{
		"id": f.nextID(), "number": n, "node_id": fmt.Sprintf("PR_%d", n), "title": title, "body": body,
		"state": "open", "merged": false, "merged_at": nil, "closed_at": nil, "auto_merge": nil,
		"mergeable_state": "blocked", "user": obj{"login": f.Login},
		"head": obj{"ref": head}, "base": obj{"ref": base},
		"html_url":   fmt.Sprintf("https://github.com/%s/pull/%d", r.name, n),
		"created_at": at, "updated_at": at,
	}
	r.pulls[n], r.pullOrder = p, append(r.pullOrder, n)
	return p, nil
}

// enableAutoMerge turns on auto-merge, squashing, as GitHub does: never where
// the repository does not allow it, nor on a PR with nothing to wait for.
func (f *Fake) enableAutoMerge(p obj) error {
	switch {
	case f.NoAutoMerge:
		return refuse(422, "Auto merge is not allowed for this repository (enablePullRequestAutoMerge)")
	case p["state"] != "open":
		return refuse(422, "Pull request is not open (enablePullRequestAutoMerge)")
	case p["mergeable_state"] == "clean":
		return refuse(422, "Pull request Pull request is in clean status (enablePullRequestAutoMerge)")
	}
	p["auto_merge"] = obj{"merge_method": "squash"}
	return nil
}

// GraphQL answers the one mutation SE sends, turning on auto-merge.
func (f *Fake) GraphQL(query string, vars ...Field) ([]byte, error) {
	defer f.spend(1)
	f.mu.Lock()
	defer f.mu.Unlock()
	f.writes = append(f.writes, "POST graphql")
	if err := f.admit(true); err != nil {
		return nil, err
	}
	f.catchUp()
	if f.Proxy {
		return nil, refuse(403, "GitHub GraphQL is not available from Claude Code sessions; use the REST API")
	}
	if !strings.Contains(query, "enablePullRequestAutoMerge") {
		return nil, refuse(422, "the fake answers no such GraphQL query")
	}
	id, _ := values(vars)["id"].(string)
	for _, r := range f.repos {
		for _, p := range r.pulls {
			if p["node_id"] == id {
				if err := f.enableAutoMerge(p); err != nil {
					return nil, err
				}
				return []byte(`{"data":{"enablePullRequestAutoMerge":{"clientMutationId":null}}}`), nil
			}
		}
	}
	return nil, refuse(0, "GraphQL: Could not resolve to a node with the global id of '"+id+"'")
}

// merge lays from over into: an object in both is merged in turn, and any
// other field from replaces into's.
func merge(into, from obj) {
	for k, v := range from {
		if sub, ok := v.(obj); ok {
			if held, ok := into[k].(obj); ok {
				merge(held, sub)
				continue
			}
		}
		into[k] = v
	}
}

// put adds or merges an issue: the fields it names replace the ones held.
func (r *repo) put(i obj) {
	n := numberOf(i)
	held, ok := r.issues[n]
	if !ok {
		held = obj{}
		r.issues[n], r.order = held, append(r.order, n)
	}
	r.seen[n] = true
	merge(held, i)
	if _, ok := held["id"]; !ok {
		held["id"] = int64(100_000_000 + n)
	}
	held["number"] = n
}

func (r *repo) putPull(p obj) {
	n := numberOf(p)
	held, ok := r.pulls[n]
	if !ok {
		held = obj{}
		r.pulls[n], r.pullOrder = held, append(r.pullOrder, n)
	}
	merge(held, p)
	held["number"] = n
	if _, ok := held["base"]; !ok {
		held["base"] = obj{"ref": "main"}
	}
}

// DeleteIssue is a person deleting issue n of repository name (OWNER/NAME):
// GitHub answers 410 Gone for it from then on, and never gives its number
// to another issue.
func (f *Fake) DeleteIssue(name string, n int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r := f.repo(name)
	delete(r.issues, n)
	delete(r.seen, n)
	r.deleted[n] = true
	kept := r.order[:0]
	for _, m := range r.order {
		if m != n {
			kept = append(kept, m)
		}
	}
	r.order = kept
}

// SeedAt is Seed once the fake's clock reaches at: what GitHub comes to hold
// by then, as a background job of its own finishes, such as a PR's
// mergeability, computed some time after it was first asked.
// Each answer must be JSON.
func (f *Fake) SeedAt(at time.Time, answers map[string]string) error {
	for p, a := range answers {
		if !json.Valid([]byte(a)) {
			return fmt.Errorf("seeding %s: not JSON", p)
		}
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.later = append(f.later, timed{at, answers})
	sort.SliceStable(f.later, func(i, j int) bool { return f.later[i].at.Before(f.later[j].at) })
	return nil
}

// catchUp seeds what the repository has come to hold by now; SeedAt checked
// that each answer is JSON.
func (f *Fake) catchUp() {
	for len(f.later) > 0 && !f.clock.Now().Before(f.later[0].at) {
		next := f.later[0]
		f.later = f.later[1:]
		_ = f.seedAll(next.answers)
	}
}

// Seed fills the fake from recorded gh answers, path to answer: a list of
// issues adds them, with the state and labels the path asked for; an issue's
// comments, sub-issues or blocked-by links set them; matching refs add the
// branches; a list of pull requests adds them, with the state, base and head
// the path asked for. Any other answer is kept for its path, read-only. The
// answers are read in the order of their paths.
func (f *Fake) Seed(answers map[string]string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.seedAll(answers)
}

func (f *Fake) seedAll(answers map[string]string) error {
	paths := make([]string, 0, len(answers))
	for p := range answers {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	for _, p := range paths {
		if err := f.seed(p, answers[p]); err != nil {
			return fmt.Errorf("seeding %s: %w", p, err)
		}
	}
	return nil
}

func decode(answer string, into any) error {
	dec := json.NewDecoder(bytes.NewReader([]byte(answer)))
	dec.UseNumber()
	return dec.Decode(into)
}

func (f *Fake) seed(path, answer string) error {
	name, w, q, err := route(path)
	if err != nil {
		return err
	}
	r := f.repo(name)
	// A list recorded with --paginate is one JSON array per page.
	var list []obj
	listed := func() error {
		dec := json.NewDecoder(bytes.NewReader([]byte(answer)))
		dec.UseNumber()
		for {
			var page []obj
			if err := dec.Decode(&page); errors.Is(err, io.EOF) {
				return nil
			} else if err != nil {
				return err
			}
			list = append(list, page...)
		}
	}
	// A list of links shows each issue it names as GitHub held it then;
	// what the fake holds of an issue already stands.
	numbers := func() ([]int, error) {
		if err := listed(); err != nil {
			return nil, err
		}
		var ns []int
		for _, i := range list {
			n := numberOf(i)
			if n == 0 {
				return nil, fmt.Errorf("an issue without a number")
			}
			if held, ok := r.issues[n]; ok {
				for k := range held {
					delete(i, k)
				}
			}
			i["number"] = n
			r.put(i)
			ns = append(ns, n)
		}
		return ns, nil
	}
	switch {
	case match(w, "issues"):
		if err := listed(); err != nil {
			return err
		}
		for _, i := range list {
			if st := q.Get("state"); st != "all" {
				if st == "" {
					st = "open"
				}
				i["state"] = st
			}
			if l := q.Get("labels"); l != "" {
				have := labelsOf(i)
				ls := asList(i["labels"])
				for _, want := range strings.Split(l, ",") {
					if !containsString(have, want) {
						ls = append(ls, obj{"name": want})
					}
				}
				i["labels"] = ls
			}
			r.put(i)
		}
		return nil
	case match(w, "issues", "#"):
		var i obj
		if err := decode(answer, &i); err != nil {
			return err
		}
		if p, ok := i["pull_request"]; ok && p != nil {
			return f.seedPull(r, num(w[1]), i)
		}
		i["number"] = num(w[1])
		r.put(i)
		return nil
	case match(w, "issues", "#", "comments"):
		if err := listed(); err != nil {
			return err
		}
		n := num(w[1])
		r.seen[n] = true
		r.comments[n] = list
		for _, c := range list {
			if idOf(c) == 0 {
				c["id"] = f.nextID()
			}
		}
		return nil
	case match(w, "issues", "#", "sub_issues"):
		ns, err := numbers()
		r.seen[num(w[1])], r.subs[num(w[1])] = true, ns
		return err
	case match(w, "issues", "#", "dependencies", "blocked_by"):
		ns, err := numbers()
		r.seen[num(w[1])], r.blockedBy[num(w[1])] = true, ns
		return err
	case match(w, "issues", "#", "dependencies", "blocking"):
		ns, err := numbers()
		n := num(w[1])
		r.seen[n] = true
		for _, m := range ns {
			if !contains(r.blockedBy[m], n) {
				r.blockedBy[m] = append(r.blockedBy[m], n)
			}
		}
		return err
	case len(w) > 2 && w[0] == "git" && w[1] == "matching-refs":
		if err := listed(); err != nil {
			return err
		}
		for _, ref := range list {
			name, _ := ref["ref"].(string)
			if name == "" {
				return fmt.Errorf("a ref without its name")
			}
			r.refs[name] = ref
		}
		return nil
	case match(w, "pulls"):
		if err := listed(); err != nil {
			return err
		}
		for _, p := range list {
			if st := q.Get("state"); st != "all" {
				if st == "" {
					st = "open"
				}
				p["state"] = st
			}
			if b := q.Get("base"); b != "" {
				p["base"] = obj{"ref": b}
			}
			if h := q.Get("head"); h != "" {
				_, branch, _ := strings.Cut(h, ":")
				p["head"] = obj{"ref": branch, "label": h}
			}
			r.putPull(p)
		}
		return nil
	case match(w, "pulls", "#"):
		var p obj
		if err := decode(answer, &p); err != nil {
			return err
		}
		p["number"] = num(w[1])
		r.putPull(p)
		return nil
	}
	if !json.Valid([]byte(answer)) {
		return fmt.Errorf("not JSON")
	}
	r.docs[path] = []byte(answer)
	return nil
}

// seedPull holds a pull request recorded through the issues route.
func (f *Fake) seedPull(r *repo, n int, i obj) error {
	p := obj{"number": n}
	for _, k := range []string{"title", "body", "state", "html_url"} {
		if v, ok := i[k]; ok {
			p[k] = v
		}
	}
	r.putPull(p)
	return nil
}
