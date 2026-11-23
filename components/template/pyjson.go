package template

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
	"unicode/utf16"
)

// pyJSON is Python's json.loads, as its C scanner reads a text: the same values (an Object keeps its
// keys' order, an integer stays an integer, NaN and Infinity are numbers) and, where the text is no
// JSON, the same error, `<what>: line <n> column <n> (char <n>)`, its places counted in characters.
// An adapter's `json_after` refusal quotes that error (templates.py `_json_after`).
func pyJSON(text string) (any, error) {
	d := &jsonReader{s: []rune(text)}
	if len(d.s) > 0 && d.s[0] == '\ufeff' {
		return nil, d.fail("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0)
	}
	at := d.space(0)
	v, end, err := d.value(at)
	if err != nil {
		return nil, err
	}
	end = d.space(end)
	if end != len(d.s) {
		return nil, d.fail("Extra data", end)
	}
	return v, nil
}

type jsonReader struct{ s []rune }

// jsonError is Python's json.JSONDecodeError: its text, and what, its msg without the place.
type jsonError struct{ msg, what string }

func (e *jsonError) Error() string { return e.msg }

// stop is Python's StopIteration from the scanner: no value starts at the place.
type stop struct{ at int }

func (e *stop) Error() string { return "stop" }

func (d *jsonReader) fail(what string, at int) error {
	line, col := 1, at+1
	for i := 0; i < at && i < len(d.s); i++ {
		if d.s[i] == '\n' {
			line, col = line+1, at-i
		}
	}
	return &jsonError{fmt.Sprintf("%s: line %d column %d (char %d)", what, line, col, at), what}
}

func jsonSpace(r rune) bool { return r == ' ' || r == '\t' || r == '\n' || r == '\r' }

func (d *jsonReader) space(at int) int {
	for at < len(d.s) && jsonSpace(d.s[at]) {
		at++
	}
	return at
}

func (d *jsonReader) at(i int) rune {
	if i < len(d.s) {
		return d.s[i]
	}
	return -1
}

func (d *jsonReader) has(i int, word string) bool {
	w := []rune(word)
	return i+len(w) <= len(d.s) && string(d.s[i:i+len(w)]) == word
}

// value is the scanner's scan_once; a *stop names where no value starts, which the caller reports
// as "Expecting value".
func (d *jsonReader) value(at int) (any, int, error) {
	v, end, err := d.scan(at)
	if s, ok := err.(*stop); ok {
		return nil, 0, d.fail("Expecting value", s.at)
	}
	return v, end, err
}

func (d *jsonReader) scan(at int) (any, int, error) {
	if at >= len(d.s) {
		return nil, 0, &stop{at}
	}
	switch d.s[at] {
	case '"':
		return d.str(at + 1)
	case '{':
		return d.object(at + 1)
	case '[':
		return d.array(at + 1)
	case 'n':
		if d.has(at, "null") {
			return nil, at + 4, nil
		}
	case 't':
		if d.has(at, "true") {
			return true, at + 4, nil
		}
	case 'f':
		if d.has(at, "false") {
			return false, at + 5, nil
		}
	case 'N':
		if d.has(at, "NaN") {
			return math.NaN(), at + 3, nil
		}
	case 'I':
		if d.has(at, "Infinity") {
			return math.Inf(1), at + 8, nil
		}
	case '-':
		if d.has(at, "-Infinity") {
			return math.Inf(-1), at + 9, nil
		}
	}
	return d.number(at)
}

func digit(r rune) bool { return r >= '0' && r <= '9' }

func (d *jsonReader) number(start int) (any, int, error) {
	i, last := start, len(d.s)-1
	if d.s[i] == '-' {
		i++
		if i > last {
			return nil, 0, &stop{start}
		}
	}
	switch {
	case d.s[i] >= '1' && d.s[i] <= '9':
		i++
		for i <= last && digit(d.s[i]) {
			i++
		}
	case d.s[i] == '0':
		i++
	default:
		return nil, 0, &stop{start}
	}
	float := false
	if i < last && d.s[i] == '.' && digit(d.s[i+1]) {
		float = true
		i += 2
		for i <= last && digit(d.s[i]) {
			i++
		}
	}
	if i < last && (d.s[i] == 'e' || d.s[i] == 'E') {
		e := i
		i++
		if i < last && (d.s[i] == '-' || d.s[i] == '+') {
			i++
		}
		for i <= last && digit(d.s[i]) {
			i++
		}
		if digit(d.s[i-1]) {
			float = true
		} else {
			i = e
		}
	}
	text := string(d.s[start:i])
	if float {
		f, _ := strconv.ParseFloat(text, 64) // out of range: ±Inf or 0, as Python's float()
		return f, i, nil
	}
	if n, err := strconv.Atoi(text); err == nil {
		return n, i, nil
	}
	n, _ := new(big.Int).SetString(text, 10)
	return n, i, nil
}

func (d *jsonReader) str(end int) (any, int, error) {
	begin := end - 1
	var b strings.Builder
	for {
		next := end
		var c rune = -1
		for ; next < len(d.s); next++ {
			c = d.s[next]
			if c == '"' || c == '\\' {
				break
			}
			if c <= 0x1f {
				return nil, 0, d.fail("Invalid control character at", next)
			}
		}
		if next >= len(d.s) || !(c == '"' || c == '\\') {
			return nil, 0, d.fail("Unterminated string starting at", begin)
		}
		b.WriteString(string(d.s[end:next]))
		next++
		if c == '"' {
			return b.String(), next, nil
		}
		if next == len(d.s) {
			return nil, 0, d.fail("Unterminated string starting at", begin)
		}
		c = d.s[next]
		if c != 'u' {
			end = next + 1
			escaped, ok := map[rune]rune{'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}[c]
			if !ok {
				return nil, 0, d.fail("Invalid \\escape", end-2)
			}
			b.WriteRune(escaped)
			continue
		}
		next++
		end = next + 4
		if end >= len(d.s) {
			return nil, 0, d.fail("Invalid \\uXXXX escape", next-1)
		}
		c, ok := hex4(d.s[next:end])
		if !ok {
			return nil, 0, d.fail("Invalid \\uXXXX escape", end-5)
		}
		if utf16.IsSurrogate(c) && c < 0xdc00 && end+6 < len(d.s) && d.s[end] == '\\' && d.s[end+1] == 'u' {
			c2, ok := hex4(d.s[end+2 : end+6])
			if !ok {
				return nil, 0, d.fail("Invalid \\uXXXX escape", end+1)
			}
			if c2 >= 0xdc00 && c2 <= 0xdfff {
				c, end = utf16.DecodeRune(c, c2), end+6
			}
		}
		b.WriteRune(c) // a lone surrogate, which Python keeps, is U+FFFD in Go's text
	}
}

func hex4(r []rune) (rune, bool) {
	n, err := strconv.ParseUint(string(r), 16, 32)
	if err != nil || len(r) != 4 || strings.ContainsAny(string(r), "+-xX_") {
		return 0, false
	}
	return rune(n), true
}

func (d *jsonReader) object(at int) (any, int, error) {
	obj := Object{}
	at = d.space(at)
	if d.at(at) != '}' {
		for {
			if d.at(at) != '"' {
				return nil, 0, d.fail("Expecting property name enclosed in double quotes", at)
			}
			key, next, err := d.str(at + 1)
			if err != nil {
				return nil, 0, err
			}
			at = d.space(next)
			if d.at(at) != ':' {
				return nil, 0, d.fail("Expecting ':' delimiter", at)
			}
			at = d.space(at + 1)
			v, next, err := d.scan(at)
			if err != nil {
				return nil, 0, err
			}
			obj.Set(key.(string), v)
			at = d.space(next)
			if d.at(at) == '}' {
				break
			}
			if d.at(at) != ',' {
				return nil, 0, d.fail("Expecting ',' delimiter", at)
			}
			comma := at
			at = d.space(at + 1)
			if d.at(at) == '}' {
				return nil, 0, d.fail("Illegal trailing comma before end of object", comma)
			}
		}
	}
	return obj, at + 1, nil
}

func (d *jsonReader) array(at int) (any, int, error) {
	list := []any{}
	at = d.space(at)
	if d.at(at) != ']' {
		for {
			v, next, err := d.scan(at)
			if err != nil {
				return nil, 0, err
			}
			list = append(list, v)
			at = d.space(next)
			if d.at(at) == ']' {
				break
			}
			if d.at(at) != ',' {
				return nil, 0, d.fail("Expecting ',' delimiter", at)
			}
			comma := at
			at = d.space(at + 1)
			if d.at(at) == ']' {
				return nil, 0, d.fail("Illegal trailing comma before end of array", comma)
			}
		}
	}
	return list, at + 1, nil
}
