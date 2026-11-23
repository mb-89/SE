package template

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// The engine reads and writes text as the Python engine does (scripts/templates.py), so the helpers
// here are Python's: its line breaks, its whitespace, its repr of a value in a message.

// isLineBreak reports whether r ends a line as Python's str.splitlines reads one.
func isLineBreak(r rune) bool {
	switch r {
	case '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
		return true
	}
	return false
}

// splitLines is Python's text.splitlines(keepends): its lines, a "\r\n" one break.
func splitLines(text string, keep bool) []string {
	var lines []string
	start := 0
	for i := 0; i < len(text); {
		r, size := utf8.DecodeRuneInString(text[i:])
		if !isLineBreak(r) {
			i += size
			continue
		}
		end := i + size
		if r == '\r' && end < len(text) && text[end] == '\n' {
			end++
		}
		if keep {
			lines = append(lines, text[start:end])
		} else {
			lines = append(lines, text[start:i])
		}
		start, i = end, end
	}
	if start < len(text) {
		lines = append(lines, text[start:])
	}
	return lines
}

// isSpace is Python's str.isspace for one character.
func isSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// strip is Python's text.strip().
func strip(text string) string { return strings.TrimFunc(text, isSpace) }

func lstrip(text string) string { return strings.TrimLeftFunc(text, isSpace) }

func rstrip(text string) string { return strings.TrimRightFunc(text, isSpace) }

// words is Python's text.split(): its runs of non-space.
func words(text string) []string { return strings.FieldsFunc(text, isSpace) }

// joinWords is Python's " ".join(text.split()).
func joinWords(text string) string { return strings.Join(words(text), " ") }

// casefold is Python's casefold, near enough for SE's texts.
func casefold(text string) string { return strings.ToLower(text) }

// chars is Python's len of a text: its characters.
func chars(text string) int { return utf8.RuneCountInString(text) }

// endLine gives text its closing line break.
func endLine(text string) string {
	if strings.HasSuffix(text, "\n") {
		return text
	}
	return text + "\n"
}

// repr is Python's repr of a value as a message writes it: a string quoted, None, True and False,
// a number, a list or a mapping.
func repr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return reprString(x)
	case bool:
		if x {
			return "True"
		}
		return "False"
	case int:
		return strconv.Itoa(x)
	case float64:
		return pyFloat(x)
	case *big.Int:
		return x.String()
	case []any:
		parts := make([]string, len(x))
		for i, item := range x {
			parts[i] = repr(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case Object:
		parts := make([]string, len(x))
		for i, pair := range x {
			parts[i] = reprString(pair.Key) + ": " + repr(pair.Value)
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return fmt.Sprint(v)
}

// pyFloat is Python's repr of a float: the shortest digits that read back, in positional
// notation from 1e-4 up to 1e16, where a whole number keeps its ".0".
func pyFloat(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	exp := 0
	if f != 0 {
		exp = int(math.Floor(math.Log10(math.Abs(f))))
		digits := strconv.FormatFloat(f, 'e', -1, 64)
		if at := strings.LastIndexByte(digits, 'e'); at >= 0 {
			exp, _ = strconv.Atoi(digits[at+1:])
		}
	}
	if exp < -4 || exp >= 16 {
		return strconv.FormatFloat(f, 'e', -1, 64)
	}
	text := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.ContainsAny(text, ".") {
		text += ".0"
	}
	return text
}

func reprString(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, "\"") {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == rune(quote):
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		case !unicode.IsPrint(r) && r != ' ':
			switch {
			case r <= 0xff:
				fmt.Fprintf(&b, `\x%02x`, r)
			case r <= 0xffff:
				fmt.Fprintf(&b, `\u%04x`, r)
			default:
				fmt.Fprintf(&b, `\U%08x`, r)
			}
		default:
			b.WriteRune(r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// str is Python's str() of a value from the front matter or a field.
func str(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case string:
		return x
	case bool, int, float64:
		return repr(x)
	case []any, Object:
		return repr(x)
	}
	return fmt.Sprint(v)
}

// truthy is Python's bool() of a value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case int:
		return x != 0
	case float64:
		return x != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case []string:
		return len(x) > 0
	case Object:
		return len(x) > 0
	}
	return true
}

// Pair is one key of a mapping and its value.
type Pair struct {
	Key   string
	Value any
}

// Object is a mapping that keeps its keys' order, as Python's dict does: the front matter's
// mappings, an object field's lines, a checklist's entries.
type Object []Pair

// Get answers the value at key.
func (o Object) Get(key string) (any, bool) {
	for _, pair := range o {
		if pair.Key == key {
			return pair.Value, true
		}
	}
	return nil, false
}

// Value answers the value at key, nil where there is none.
func (o Object) Value(key string) any {
	v, _ := o.Get(key)
	return v
}

// Has reports whether the mapping holds key.
func (o Object) Has(key string) bool {
	_, ok := o.Get(key)
	return ok
}

// Set writes key, in its place where it stands, else last.
func (o *Object) Set(key string, v any) {
	for i := range *o {
		if (*o)[i].Key == key {
			(*o)[i].Value = v
			return
		}
	}
	*o = append(*o, Pair{key, v})
}

// Delete takes key out.
func (o *Object) Delete(key string) {
	for i := range *o {
		if (*o)[i].Key == key {
			*o = append((*o)[:i:i], (*o)[i+1:]...)
			return
		}
	}
}

// Keys answers the keys in order.
func (o Object) Keys() []string {
	keys := make([]string, len(o))
	for i, pair := range o {
		keys[i] = pair.Key
	}
	return keys
}

// Copy answers a copy whose values are copied too.
func (o Object) Copy() Object {
	out := make(Object, len(o))
	for i, pair := range o {
		out[i] = Pair{pair.Key, copyValue(pair.Value)}
	}
	return out
}

func copyValue(v any) any {
	switch x := v.(type) {
	case Object:
		return x.Copy()
	case []any:
		out := make([]any, len(x))
		for i, item := range x {
			out[i] = copyValue(item)
		}
		return out
	}
	return v
}

// MarshalJSON writes the mapping as a JSON object in its order.
func (o Object) MarshalJSON() ([]byte, error) {
	var b strings.Builder
	b.WriteByte('{')
	for i, pair := range o {
		if i > 0 {
			b.WriteByte(',')
		}
		key, _ := json.Marshal(pair.Key)
		value, err := json.Marshal(pair.Value)
		if err != nil {
			return nil, err
		}
		b.Write(key)
		b.WriteByte(':')
		b.Write(value)
	}
	b.WriteByte('}')
	return []byte(b.String()), nil
}

// UnmarshalJSON reads a JSON object in its order, its values as decodeJSON gives them.
func (o *Object) UnmarshalJSON(data []byte) error {
	v, err := decodeJSON(string(data))
	if err != nil {
		return err
	}
	obj, ok := v.(Object)
	if !ok {
		return fmt.Errorf("not a JSON object")
	}
	*o = obj
	return nil
}

// decodeJSON reads one JSON value as Python's json.loads does: an object as an Object in its
// order, a whole number as an int, every other number as a float64.
func decodeJSON(text string) (any, error) {
	dec := json.NewDecoder(strings.NewReader(text))
	dec.UseNumber()
	v, err := decodeValue(dec)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); err == nil {
		return nil, fmt.Errorf("Extra data")
	}
	return v, nil
}

func decodeValue(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	switch t := tok.(type) {
	case json.Delim:
		switch t {
		case '{':
			obj := Object{}
			for dec.More() {
				keyTok, err := dec.Token()
				if err != nil {
					return nil, err
				}
				key, _ := keyTok.(string)
				value, err := decodeValue(dec)
				if err != nil {
					return nil, err
				}
				obj.Set(key, value)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return obj, nil
		case '[':
			list := []any{}
			for dec.More() {
				value, err := decodeValue(dec)
				if err != nil {
					return nil, err
				}
				list = append(list, value)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return list, nil
		}
		return nil, fmt.Errorf("unexpected %v", t)
	case json.Number:
		if i, err := strconv.Atoi(t.String()); err == nil {
			return i, nil
		}
		f, err := t.Float64()
		return f, err
	}
	return tok, nil
}

// equal is Python's == of two values: a mapping's keys in any order.
func equal(a, b any) bool {
	switch x := a.(type) {
	case Object:
		y, ok := b.(Object)
		if !ok || len(x) != len(y) {
			return false
		}
		for _, pair := range x {
			other, ok := y.Get(pair.Key)
			if !ok || !equal(pair.Value, other) {
				return false
			}
		}
		return true
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !equal(x[i], y[i]) {
				return false
			}
		}
		return true
	case int:
		switch y := b.(type) {
		case int:
			return x == y
		case float64:
			return float64(x) == y
		case bool:
			return (x == 1 && y) || (x == 0 && !y)
		}
		return false
	}
	return a == b
}

// quoteMeta is Python's re.escape, as far as RE2 needs it.
func quoteMeta(text string) string { return regexp.QuoteMeta(text) }

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// joinStrings is Python's ", ".join of the texts.
func joinStrings(items []string) string { return strings.Join(items, ", ") }
