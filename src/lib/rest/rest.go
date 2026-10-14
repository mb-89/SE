// Package rest is what a module asks of GitHub's REST API, as the requests of
// io/github's verbs get, list and send: the I/O module answers them, and a
// compute module asks them through its request ports. Both ends of a wire
// share one Go type, so the types live here, which both import.
package rest

import "strconv"

// Get is a request of the get verb: the JSON value at Path, such as
// repos/OWNER/NAME/issues/5.
type Get struct{ Path string }

// List is a request of the list verb: every item of the paginated list at
// Path, every page of it, as one JSON array.
type List struct{ Path string }

// Send is a request of the send verb: Method (POST, PATCH, PUT or DELETE)
// to Path with Fields.
type Send struct {
	Method, Path string
	Fields       []Field
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
