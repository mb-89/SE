package github

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// attempts is how often a read is sent before a rate limit fails it.
const attempts = 4

// secondaryWait is the wait a 403 or 429 without Retry-After and without an
// exhausted quota asks: GitHub's guidance for its secondary limits is to wait
// at least a minute.
const secondaryWait = time.Minute

// rest is the token backend's REST client. It keeps each path's ETag and
// body, so a read of an unchanged one answers 304 and costs no quota, and
// one pace: after a rate limit, every read waits until it lifts.
type rest struct {
	api, token string
	client     *http.Client
	sleep      func(time.Duration)
	now        func() time.Time
	paceMax    time.Duration

	mu    sync.Mutex
	cache map[string]cached
	until time.Time // no read goes out before it
}

type cached struct {
	etag string
	body any
	next bool // whether the answer's Link names a next page
}

// repoPath is a repository's REST path.
func repoPath(owner, repo string) string {
	return "/repos/" + url.PathEscape(strings.ToLower(owner)) + "/" + url.PathEscape(strings.ToLower(repo))
}

// read answers a kind's read: a check-runs read first reads the pull request
// for its head; a comments read reads every page.
func (c *rest) read(k kind, r Ref) (any, error) {
	base := repoPath(r.Owner, r.Repo)
	switch k.port {
	case comments.port:
		return c.pages(fmt.Sprintf("%s/issues/%d/comments", base, r.Number), url.Values{}, func(any) bool { return true })
	case issues.port:
		return c.get(fmt.Sprintf("%s/issues/%d", base, r.Number))
	case pulls.port:
		return c.get(fmt.Sprintf("%s/pulls/%d", base, r.Number))
	}
	pr, err := c.get(fmt.Sprintf("%s/pulls/%d", base, r.Number))
	if err != nil {
		return nil, err
	}
	head, _ := pr.(map[string]any)["head"].(map[string]any)
	sha, _ := head["sha"].(string)
	if sha == "" {
		return nil, fmt.Errorf("pull request %d names no head", r.Number)
	}
	return c.get(fmt.Sprintf("%s/commits/%s/check-runs", base, sha))
}

// pages reads every page of a list at path with the query q, perPage items
// a page, each page with its own ETag, until a page's Link names no next;
// it keeps the items keep takes.
func (c *rest) pages(path string, q url.Values, keep func(any) bool) ([]any, error) {
	items := []any{}
	for page := 1; ; page++ {
		q.Set("per_page", strconv.Itoa(perPage))
		q.Set("page", strconv.Itoa(page))
		body, next, err := c.page(path + "?" + q.Encode())
		if err != nil {
			return nil, err
		}
		got, ok := body.([]any)
		if !ok {
			return nil, fmt.Errorf("GET %s page %d: the answer is no list", path, page)
		}
		for _, item := range got {
			if keep(item) {
				items = append(items, item)
			}
		}
		if !next {
			return items, nil
		}
	}
}

// get reads one path, as page does, without its next.
func (c *rest) get(path string) (any, error) {
	body, _, err := c.page(path)
	return body, err
}

// page reads one path, with its ETag where it holds one, waiting out a rate
// limit up to paceMax each time and attempts times in all; it answers the
// body and whether its Link header names a next page.
func (c *rest) page(path string) (any, bool, error) {
	for attempt := 1; ; attempt++ {
		c.mu.Lock()
		wait := c.until.Sub(c.now())
		prev, held := c.cache[path]
		c.mu.Unlock()
		if wait > 0 {
			if wait > c.paceMax {
				return nil, false, fmt.Errorf("GET %s: rate limited for %v more, over pace-max %v", path, wait.Round(time.Second), c.paceMax)
			}
			c.sleep(wait)
		}
		req, err := http.NewRequest(http.MethodGet, c.api+path, nil)
		if err != nil {
			return nil, false, err
		}
		req.Header.Set("Accept", "application/vnd.github+json")
		req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
		req.Header.Set("Authorization", "Bearer "+c.token)
		if held {
			req.Header.Set("If-None-Match", prev.etag)
		}
		resp, err := c.client.Do(req)
		if err != nil {
			return nil, false, fmt.Errorf("GET %s: %w", path, err)
		}
		body, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			return nil, false, fmt.Errorf("GET %s: %w", path, err)
		}
		switch {
		case resp.StatusCode == http.StatusNotModified && held:
			return prev.body, prev.next, nil
		case resp.StatusCode == http.StatusOK:
			var v any
			if err := json.Unmarshal(body, &v); err != nil {
				return nil, false, fmt.Errorf("GET %s: the answer is no JSON: %w", path, err)
			}
			next := hasNext(resp.Header.Get("Link"))
			if etag := resp.Header.Get("ETag"); etag != "" {
				c.mu.Lock()
				c.cache[path] = cached{etag: etag, body: v, next: next}
				c.mu.Unlock()
			}
			return v, next, nil
		}
		pace, limited := c.limit(resp)
		if !limited {
			return nil, false, fmt.Errorf("GET %s: %s: %.200s", path, resp.Status, body)
		}
		if attempt == attempts {
			return nil, false, fmt.Errorf("GET %s: %s, rate limited %d times", path, resp.Status, attempts)
		}
		c.mu.Lock()
		if until := c.now().Add(pace); until.After(c.until) {
			c.until = until
		}
		c.mu.Unlock()
	}
}

// limit answers how long a refusal asks to wait, where it is a rate limit:
// a 429, or a 403 with Retry-After or an exhausted quota. Retry-After wins,
// then the quota's reset, then a minute.
func (c *rest) limit(resp *http.Response) (time.Duration, bool) {
	h := resp.Header
	switch {
	case resp.StatusCode == http.StatusTooManyRequests:
	case resp.StatusCode == http.StatusForbidden && (h.Get("Retry-After") != "" || h.Get("X-RateLimit-Remaining") == "0"):
	default:
		return 0, false
	}
	if s, err := strconv.Atoi(h.Get("Retry-After")); err == nil && s >= 0 {
		return time.Duration(s) * time.Second, true
	}
	if h.Get("X-RateLimit-Remaining") == "0" {
		if reset, err := strconv.ParseInt(h.Get("X-RateLimit-Reset"), 10, 64); err == nil {
			if d := time.Unix(reset, 0).Sub(c.now()); d > 0 {
				return d, true
			}
			return 0, true
		}
	}
	return secondaryWait, true
}

// hasNext says whether a Link header names a next page: rel="next".
func hasNext(link string) bool {
	for _, part := range strings.Split(link, ",") {
		for _, param := range strings.Split(part, ";")[1:] {
			if strings.ReplaceAll(strings.TrimSpace(param), " ", "") == `rel="next"` {
				return true
			}
		}
	}
	return false
}
