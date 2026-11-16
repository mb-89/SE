// Package home answers a checkout's home from its origin: the host, owner and
// repository it lives at, so no file needs to name them. The same tree may
// live on more than one Git host, and only a machine that holds both remotes
// knows that; nothing here guesses a home.
//
// It answers as SE's Python helper does (SE's scripts/se_home.py): both read
// the one table of origins and answers in testdata/origins.json in their
// tests, so the two never drift.
//
//   - Parse reads an https origin (with or without credentials) or an ssh one
//     (ssh://[user@]host/... or [user@]host:owner/repository); any other form,
//     such as a local proxy's http URL or a path, has no home.
//   - Of reads the checkout's origin through kern's git door.
//   - Home.URL, Home.Tracker and Home.Docs are its answers; Home.At a path
//     under it, such as a release's download base.
package home

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"kern/git"
)

// GitHub is the host whose homes have a documentation site, GitHub Pages.
const GitHub = "github.com"

// Home is where a checkout lives: a host, an owner and a repository.
type Home struct {
	Host       string `json:"host"`
	Owner      string `json:"owner"`
	Repository string `json:"repository"`
}

// URL is https://<host>/<owner>/<repository>.
func (h Home) URL() string { return "https://" + h.Host + "/" + h.Owner + "/" + h.Repository }

// Tracker is <owner>/<repository>.
func (h Home) Tracker() string { return h.Owner + "/" + h.Repository }

// Docs is the GitHub Pages site of a home on github.com, and "" on any other host.
func (h Home) Docs() string {
	if !strings.EqualFold(h.Host, GitHub) {
		return ""
	}
	return "https://" + strings.ToLower(h.Owner) + ".github.io/" + h.Repository + "/"
}

// At is a path under the home's URL, such as releases/download/<tag>.
func (h Home) At(path string) string { return h.URL() + "/" + strings.TrimLeft(path, "/") }

// Named is <host>/<owner>/<repository> of a setting's repository: a bare name
// lies beside the home, <owner>/<repository> on its host; a longer one stays.
func (h Home) Named(entry string) string {
	entry = strings.Trim(entry, "/")
	switch parts := strings.Split(entry, "/"); len(parts) {
	case 1:
		return h.Host + "/" + h.Owner + "/" + entry
	case 2:
		return h.Host + "/" + entry
	}
	return entry
}

var (
	https = regexp.MustCompile(`(?i)^https://(?:[^@/]*@)?([^/:@]+)(?::\d+)?/([^?#]+?)(?:\.git)?/?$`)
	ssh   = regexp.MustCompile(`(?i)^ssh://(?:[^@/]+@)?([^/:@]+)(?::\d+)?/([^?#]+?)(?:\.git)?/?$`)
	// [user@]host:owner/repository; a host of one letter is a Windows drive.
	scp  = regexp.MustCompile(`^(?:[^@/:]+@)?([^/:@\\]{2,}):([^\\]+?)(?:\.git)?/?$`)
	name = regexp.MustCompile(`^[\w.-]+$`)
)

// Parse answers the home an origin URL names; ok is false for a form it does
// not read.
func Parse(url string) (h Home, ok bool) {
	url = strings.TrimSpace(url)
	m := https.FindStringSubmatch(url)
	if m == nil {
		m = ssh.FindStringSubmatch(url)
	}
	if m == nil && !strings.Contains(url, "://") {
		if m = scp.FindStringSubmatch(url); m != nil && strings.HasPrefix(m[2], "//") {
			m = nil
		}
	}
	if m == nil {
		return Home{}, false
	}
	parts := strings.Split(strings.Trim(m[2], "/"), "/")
	if len(parts) != 2 || !name.MatchString(parts[0]) || !name.MatchString(parts[1]) {
		return Home{}, false
	}
	return Home{Host: strings.ToLower(m[1]), Owner: parts[0], Repository: parts[1]}, true
}

// NoHome is why a checkout's home cannot be known.
type NoHome struct{ Reason string }

func (e *NoHome) Error() string { return e.Reason }

// Origin answers the checkout's origin URL (git's insteadOf rewrites applied),
// or "" without one.
func Origin(ctx context.Context, dir string) string {
	out, err := git.Run(ctx, dir, "remote", "get-url", "origin")
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

// Of answers the home of the checkout at dir from its origin; a *NoHome, with
// its reason, where it cannot be known.
func Of(ctx context.Context, dir string) (Home, error) {
	url := Origin(ctx, dir)
	if url == "" {
		return Home{}, &NoHome{fmt.Sprintf("%s has no origin remote, so its home cannot be known", dir)}
	}
	h, ok := Parse(url)
	if !ok {
		return Home{}, &NoHome{fmt.Sprintf("the origin of %s is no https or ssh repository URL, so its home cannot be known", dir)}
	}
	return h, nil
}
