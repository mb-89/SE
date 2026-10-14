package github

import (
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mb-89/SE/src/internal/io/clock"
)

// Rate is what GitHub said of the quota with an answer: the
// x-ratelimit-limit, x-ratelimit-remaining and x-ratelimit-reset headers, and
// retry-after where it asks for a pause (a secondary limit).
type Rate struct {
	// Known is set where the answer carried the quota's headers.
	Known bool
	// Limit is the requests the hour allows, Remaining what is left of them.
	Limit, Remaining int
	// Reset is when the hour's quota starts again.
	Reset time.Time
	// RetryAfter is how long GitHub asked to wait; zero where it did not.
	RetryAfter time.Duration
}

// rateOf reads the quota from an answer's headers, named in lower case.
func rateOf(h map[string]string) Rate {
	var r Rate
	if v, ok := h["x-ratelimit-remaining"]; ok {
		r.Remaining, _ = strconv.Atoi(v)
		r.Known = true
	}
	r.Limit, _ = strconv.Atoi(h["x-ratelimit-limit"])
	if s, err := strconv.ParseInt(h["x-ratelimit-reset"], 10, 64); err == nil && s > 0 {
		r.Reset = time.Unix(s, 0).UTC()
	}
	if s, err := strconv.Atoi(h["retry-after"]); err == nil && s > 0 {
		r.RetryAfter = time.Duration(s) * time.Second
	}
	return r
}

// Meter is a GitHub that counts the requests it made and keeps what GitHub
// last said of the quota. Real, Fake and Limited are each one.
type Meter interface {
	// Requests answers how many requests went to GitHub, a List's pages each one.
	Requests() int
	// Rate answers the quota as GitHub's last answer gave it.
	Rate() Rate
}

// Metered answers g's requests and rate where g is a Meter; zero where not.
func Metered(g GitHub) (int, Rate) {
	if m, ok := g.(Meter); ok {
		return m.Requests(), m.Rate()
	}
	return 0, Rate{}
}

// Limits are how a Limited lives within GitHub's rate limits, the github
// instance's config.
type Limits struct {
	// Ceiling is the longest a command waits, all told, for GitHub's limit to
	// reset; a reset further off fails the request at once, saying when.
	Ceiling time.Duration
	// Spacing is the least time between two writes, which keeps a sweep
	// under GitHub's limit on creating content (comments, issues, labels).
	Spacing time.Duration
}

// Limited is a GitHub that lives within GitHub's rate limits: it spaces its
// writes by Spacing, one at a time, and where GitHub refuses a request for a
// rate limit (403 or 429), it says so on its writer and waits for the reset
// before it asks again, never longer than Ceiling all told.
type Limited struct {
	gh     GitHub
	clock  clock.Clock
	limits Limits
	say    io.Writer
	// writing holds one write at a time; last is when the last one ended.
	writing sync.Mutex
	last    time.Time
	// refused records each rate-limit refusal, under its own lock, since
	// reads retry side by side.
	refusing sync.Mutex
	refused  []Refusal
}

// Refusal is one request GitHub refused for a rate limit: when, with which
// HTTP status, and how long se waited for the reset before it asked again;
// GaveUp where that wait would have passed the ceiling and the request
// failed at once instead, waiting nothing.
type Refusal struct {
	At     time.Time
	Status int
	Wait   time.Duration
	GaveUp bool
}

// Refuser is a GitHub that keeps the rate-limit refusals it met: Limited.
type Refuser interface {
	// Refusals answers each rate-limit refusal met so far, oldest first.
	Refusals() []Refusal
}

// RefusedBy answers the rate-limit refusals g met where g keeps them; none
// where not.
func RefusedBy(g GitHub) []Refusal {
	if r, ok := g.(Refuser); ok {
		return r.Refusals()
	}
	return nil
}

// Limit answers gh living within GitHub's rate limits, timed by c, saying on
// say each wait for a reset before it waits.
func Limit(gh GitHub, c clock.Clock, l Limits, say io.Writer) *Limited {
	if say == nil {
		say = io.Discard
	}
	return &Limited{gh: gh, clock: c, limits: l, say: say}
}

// Get answers the JSON value at path, waiting out a rate limit.
func (l *Limited) Get(path string) ([]byte, error) {
	return l.retry(func() ([]byte, error) { return l.gh.Get(path) })
}

// List answers every page of the list at path, waiting out a rate limit.
func (l *Limited) List(path string) ([]byte, error) {
	return l.retry(func() ([]byte, error) { return l.gh.List(path) })
}

// Send sends a write, spaced from the one before it, waiting out a rate limit.
func (l *Limited) Send(method, path string, fields ...Field) ([]byte, error) {
	return l.write(func() ([]byte, error) { return l.gh.Send(method, path, fields...) })
}

// GraphQL runs a mutation, spaced as a write is, waiting out a rate limit.
func (l *Limited) GraphQL(query string, vars ...Field) ([]byte, error) {
	return l.write(func() ([]byte, error) { return l.gh.GraphQL(query, vars...) })
}

// Requests answers the requests the GitHub it wraps made.
func (l *Limited) Requests() int { n, _ := Metered(l.gh); return n }

// Rate answers the quota as the GitHub it wraps last saw it.
func (l *Limited) Rate() Rate { _, r := Metered(l.gh); return r }

// Refusals answers each rate-limit refusal it met, and the wait it made for
// each, oldest first.
func (l *Limited) Refusals() []Refusal {
	l.refusing.Lock()
	defer l.refusing.Unlock()
	return append([]Refusal(nil), l.refused...)
}

// refuse records a rate-limit refusal.
func (l *Limited) refuse(r Refusal) {
	l.refusing.Lock()
	defer l.refusing.Unlock()
	l.refused = append(l.refused, r)
}

// write makes one write at a time, at least Spacing after the last ended.
func (l *Limited) write(call func() ([]byte, error)) ([]byte, error) {
	l.writing.Lock()
	defer l.writing.Unlock()
	if !l.last.IsZero() {
		if gap := l.limits.Spacing - l.clock.Now().Sub(l.last); gap > 0 {
			l.clock.Sleep(gap)
		}
	}
	defer func() { l.last = l.clock.Now() }()
	return l.retry(call)
}

// retry makes call, and while GitHub refuses it for a rate limit, says so
// and waits for the reset, then makes it again. Each wait is at least a
// second and twice the one before, so it never asks in a tight loop; a wait
// that would take it past Ceiling all told fails the request at once.
func (l *Limited) retry(call func() ([]byte, error)) ([]byte, error) {
	var waited time.Duration
	for tries := 0; ; tries++ {
		out, err := call()
		r, limited := RateLimited(err)
		if !limited {
			return out, err
		}
		now := l.clock.Now()
		d := r.wait(now)
		d = max(d, time.Second<<min(tries, 12))
		if waited+d > l.limits.Ceiling {
			l.refuse(Refusal{At: now, Status: Status(err), GaveUp: true})
			return nil, fmt.Errorf("GitHub's rate limit holds until %s, past the %s se waits for it (github/config/wait-ceiling): %w",
				now.Add(d).UTC().Format("15:04:05 UTC"), l.limits.Ceiling, err)
		}
		fmt.Fprintf(l.say, "se: GitHub refused a request for its rate limit (HTTP %d); waiting %s, until %s, for it to reset.\n",
			Status(err), d.Round(time.Second), now.Add(d).UTC().Format("15:04:05 UTC"))
		l.refuse(Refusal{At: now, Status: Status(err), Wait: d})
		l.clock.Sleep(d)
		waited += d
	}
}

// secondaryWait is how long to wait where GitHub names a secondary limit
// without saying how long: a minute, as its documentation asks.
const secondaryWait = time.Minute

// wait is how long from now GitHub asked to wait: its retry-after, or until
// its reset, or a minute where it said neither. A reset read on a clock a
// little behind GitHub's is refused again, and retry waits longer each time.
func (r Rate) wait(now time.Time) time.Duration {
	switch {
	case r.RetryAfter > 0:
		return r.RetryAfter
	case r.Known && r.Remaining == 0 && !r.Reset.IsZero():
		return r.Reset.Sub(now)
	}
	return secondaryWait
}

// RateLimited says whether err is GitHub refusing a request for a rate
// limit, its primary one or a secondary one, and answers the quota it said
// with the refusal. A 403 for anything else, such as a permission, is none.
func RateLimited(err error) (Rate, bool) {
	var e *Error
	if !errors.As(err, &e) || (e.Status != 403 && e.Status != 429) {
		return Rate{}, false
	}
	r := e.Rate
	if e.Status == 429 || r.RetryAfter > 0 || (r.Known && r.Remaining == 0) || strings.Contains(strings.ToLower(e.Message), "rate limit") {
		return r, true
	}
	return Rate{}, false
}
