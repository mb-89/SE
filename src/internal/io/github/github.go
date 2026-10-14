// Package github is the I/O module for GitHub: the one place SE reads or
// writes issues, their links and sub-issues, branches, pull requests,
// comments and labels. Code that needs GitHub takes a GitHub as an argument;
// the se binary hands it Real, which calls GitHub's REST API in the process,
// and a test hands it a Fake, which keeps its own state, so a write is read
// back.
package github

import (
	"errors"
	"fmt"
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
	// Message is what GitHub said, after the request it refused.
	Message string
	// Rate is what GitHub said of the quota with the refusal.
	Rate Rate
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
