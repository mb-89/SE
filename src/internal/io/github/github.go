// Package github is the I/O module for GitHub: the one place SE reads or
// writes issues, their links and sub-issues, branches, pull requests,
// comments and labels. Code that needs GitHub takes a GitHub as an argument;
// the se binary hands it Real, which goes through the gh CLI, and a test hands
// it a Fake, which keeps its own state, so a write is read back.
package github

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

// GitHub is what SE asks of GitHub: its REST API, read and written by path
// (such as repos/OWNER/NAME/issues/5), and the one GraphQL mutation REST
// lacks, turning on auto-merge.
type GitHub interface {
	// Get answers the JSON value at path.
	Get(path string) ([]byte, error)
	// List answers every item of the paginated list at path, every page of
	// it, as one JSON array.
	List(path string) ([]byte, error)
	// Send sends method (POST, PATCH, PUT or DELETE) to path with fields and
	// answers GitHub's JSON reply, empty where it has none.
	Send(method, path string, fields ...Field) ([]byte, error)
	// GraphQL runs query with its variables and answers the JSON reply.
	GraphQL(query string, vars ...Field) ([]byte, error)
}

// Field is one field of a request. Name may end in [] to add to an array,
// as labels[] does.
type Field struct {
	Name, Value string
	// Typed is set for a number, true, false or null, which GitHub reads as
	// that rather than as a string.
	Typed bool
}

// F is a string field.
func F(name, value string) Field { return Field{Name: name, Value: value} }

// Int is a number field, such as the issue_id a link takes.
func Int(name string, v int64) Field {
	return Field{Name: name, Value: strconv.FormatInt(v, 10), Typed: true}
}

// Error is GitHub refusing a request, with the HTTP status it answered.
type Error struct {
	// Status is the HTTP status, such as 404; zero where none was said.
	Status int
	// Message is what GitHub, or gh, said.
	Message string
}

func (e *Error) Error() string {
	if e.Status != 0 && !strings.Contains(e.Message, "(HTTP ") {
		return fmt.Sprintf("%s (HTTP %d)", e.Message, e.Status)
	}
	return e.Message
}

// Status answers the HTTP status GitHub refused err with, or zero where err
// is no refusal of GitHub's.
func Status(err error) int {
	var e *Error
	if errors.As(err, &e) {
		return e.Status
	}
	return 0
}

// Real is GitHub through the gh CLI on this machine, which owns the
// authentication.
func Real() GitHub { return gh{} }

type gh struct{}

func (gh) Get(path string) ([]byte, error) { return run("api", path) }

// List asks for path page by page, adding page=k itself, and joins the
// pages. gh's --paginate follows GitHub's next links instead, which for some
// lists name repositories/{id}, and the cloud box proxy refuses those. A page
// shorter than per_page (30 where path does not say) is the last; so is one
// that repeats the page before it, where a list takes no page.
func (gh) List(path string) ([]byte, error) {
	sep, size := "?", 30
	if u, err := url.Parse(path); err == nil && u.RawQuery != "" {
		sep = "&"
		if n, err := strconv.Atoi(u.Query().Get("per_page")); err == nil && n > 0 {
			size = n
		}
	}
	all := []json.RawMessage{}
	var last []byte
	for k := 1; ; k++ {
		out, err := run("api", fmt.Sprintf("%s%spage=%d", path, sep, k))
		if err != nil {
			return nil, err
		}
		if k > 1 && bytes.Equal(bytes.TrimSpace(out), last) {
			return json.Marshal(all)
		}
		last = bytes.TrimSpace(out)
		var page []json.RawMessage
		if err := json.Unmarshal(out, &page); err != nil {
			return nil, fmt.Errorf("gh api %s: %v", path, err)
		}
		all = append(all, page...)
		if len(page) < size {
			return json.Marshal(all)
		}
	}
}

func (gh) Send(method, path string, fields ...Field) ([]byte, error) {
	return run(append(append([]string{"api", "-X", method}, flags(fields)...), path)...)
}

func (gh) GraphQL(query string, vars ...Field) ([]byte, error) {
	return run(append(append([]string{"api", "-f", "query=" + query}, flags(vars)...), "graphql")...)
}

func flags(fields []Field) []string {
	var out []string
	for _, f := range fields {
		flag := "-f"
		if f.Typed {
			flag = "-F"
		}
		out = append(out, flag, f.Name+"="+f.Value)
	}
	return out
}

// notSignedIn is what a command that needs GitHub says where gh has no login:
// the install never asks for one, so this is where a person learns of it.
const notSignedIn = "gh cannot reach GitHub without a login; run gh auth login, then this command again"

// httpStatus is how gh names the status of a refused request.
var httpStatus = regexp.MustCompile(`\(HTTP (\d{3})\)`)

func run(args ...string) ([]byte, error) {
	cmd := exec.Command("gh", args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrNotFound) {
		return nil, errors.New("gh is missing; RUNME.sh installs it")
	}
	if err != nil {
		said := strings.TrimSpace(stderr.String())
		e := &Error{Message: fmt.Sprintf("gh %s: %v: %s", strings.Join(args, " "), err, said)}
		if m := httpStatus.FindStringSubmatch(said); m != nil {
			e.Status, _ = strconv.Atoi(m[1])
		}
		if e.Status == 401 || strings.Contains(said, "gh auth login") {
			e.Message = notSignedIn
		}
		return nil, e
	}
	return out, nil
}
