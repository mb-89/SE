package template

import (
	"fmt"
	"regexp"
	"strings"
)

// The front matter is YAML in the subset scripts/templates.py's front_data reads (its docstring,
// "Template files"): `key: value` lines and `- ` items nested by spaces, `#` comment lines, a value
// JSON where it opens with `"`, `[` or `{`, a single-quoted string, true, false, a whole number or
// plain words; plain words another reader takes for something else are refused until quoted.

var (
	yamlKey       = regexp.MustCompile(`^("(?:[^"\\]|\\.)*"|[A-Za-z_][\w.-]*):(?:[ \t]+(.*?))?[ \t]*$`)
	yamlInt       = regexp.MustCompile(`^-?(?:0|[1-9][0-9]*)$`)
	yamlAmbiguous = regexp.MustCompile(`(?i)^(?:null|~|y|n|yes|no|on|off|true|false|-?[0-9][0-9_]*\.[0-9_]*|[-+]?\.(?:inf|nan)|0[xo][0-9a-f]+)$`)
)

const yamlIndicators = "-?:,[]{}#&*!|>'\"%@`"

type yamlLine struct {
	number, indent int
	text           string
}

func yamlLines(text, where string, first int) ([]yamlLine, error) {
	var lines []yamlLine
	for i, line := range splitLines(text, false) {
		number := first + i
		stripped := strip(line)
		if stripped == "" || strings.HasPrefix(stripped, "#") {
			continue
		}
		lead := line[:len(line)-len(lstrip(line))]
		if strings.Contains(lead, "\t") {
			return nil, fmt.Errorf("%s:%d: front matter is indented with a tab; indent with spaces", where, number)
		}
		indent := chars(line) - chars(strings.TrimLeft(line, " "))
		lines = append(lines, yamlLine{number, indent, stripped})
	}
	return lines, nil
}

func yamlScalar(text, where string) (any, error) {
	if text == "" || strings.ContainsAny(text[:1], "\"[{") {
		v, err := pyJSON(text)
		if err != nil {
			what := err.Error()
			if e, ok := err.(*jsonError); ok {
				what = e.what
			}
			return nil, fmt.Errorf("%s: %s is no JSON value (%s); write a quoted string, a list or a mapping as JSON", where, text, what)
		}
		return v, nil
	}
	if text[0] == '\'' {
		if len(text) < 2 || !strings.HasSuffix(text, "'") || strings.Contains(strings.ReplaceAll(text[1:len(text)-1], "''", ""), "'") {
			return nil, fmt.Errorf("%s: %s is no single-quoted string; double a quote inside it", where, text)
		}
		return strings.ReplaceAll(text[1:len(text)-1], "''", "'"), nil
	}
	if text == "true" || text == "false" {
		return text == "true", nil
	}
	if yamlInt.MatchString(text) {
		var n int
		if _, err := fmt.Sscan(text, &n); err == nil {
			return n, nil
		}
	}
	if yamlAmbiguous.MatchString(text) || strings.ContainsRune(yamlIndicators, rune(text[0])) ||
		strings.Contains(text, ": ") || strings.Contains(text, " #") || strings.HasSuffix(text, ":") {
		return nil, fmt.Errorf("%s: %s is a plain value another YAML reader may read otherwise; quote it as a JSON string", where, text)
	}
	return text, nil
}

func isItem(text string) bool { return text == "-" || strings.HasPrefix(text, "- ") }

func yamlBlock(lines []yamlLine, index, indent int, where string) (any, int, error) {
	line := lines[index]
	if line.indent != indent {
		return nil, 0, fmt.Errorf("%s:%d: indented %d spaces where %d are expected", where, line.number, line.indent, indent)
	}
	if isItem(line.text) {
		items := []any{}
		for index < len(lines) && lines[index].indent == indent && isItem(lines[index].text) {
			number, text := lines[index].number, lines[index].text
			rest := strip(text[1:])
			if rest == "" {
				return nil, 0, fmt.Errorf("%s:%d: an empty list item; write its value after `- `", where, number)
			}
			if yamlKey.MatchString(rest) && !strings.ContainsAny(rest[:1], "[{") {
				changed := append(append(append([]yamlLine{}, lines[:index]...), yamlLine{number, indent + 2, rest}), lines[index+1:]...)
				lines = changed
				value, next, err := yamlBlock(lines, index, indent+2, where)
				if err != nil {
					return nil, 0, err
				}
				items = append(items, value)
				index = next
				continue
			}
			value, err := yamlScalar(rest, fmt.Sprintf("%s:%d", where, number))
			if err != nil {
				return nil, 0, err
			}
			items = append(items, value)
			index++
		}
		if index < len(lines) && lines[index].indent > indent {
			return nil, 0, fmt.Errorf("%s:%d: indented deeper than its list's items", where, lines[index].number)
		}
		return items, index, nil
	}
	mapping := Object{}
	for index < len(lines) && lines[index].indent == indent {
		number, text := lines[index].number, lines[index].text
		match := yamlKey.FindStringSubmatch(text)
		if match == nil || strings.HasPrefix(text, "- ") {
			return nil, 0, fmt.Errorf("%s:%d: %s is no `key: value` line", where, number, text)
		}
		key := match[1]
		if strings.HasPrefix(key, "\"") {
			v, err := pyJSON(key)
			if err != nil {
				return nil, 0, fmt.Errorf("%s:%d: %s is no `key: value` line", where, number, text)
			}
			key, _ = v.(string)
		}
		if mapping.Has(key) {
			return nil, 0, fmt.Errorf("%s:%d: %s is given twice", where, number, key)
		}
		if match[2] != "" {
			value, err := yamlScalar(match[2], fmt.Sprintf("%s:%d", where, number))
			if err != nil {
				return nil, 0, err
			}
			mapping.Set(key, value)
			index++
			if index < len(lines) && lines[index].indent > indent {
				return nil, 0, fmt.Errorf("%s:%d: indented below a key that has its value", where, lines[index].number)
			}
			continue
		}
		if index+1 >= len(lines) || lines[index+1].indent <= indent {
			return nil, 0, fmt.Errorf("%s:%d: %s has no value; write it after the colon, or indent its mapping or list below it", where, number, key)
		}
		value, next, err := yamlBlock(lines, index+1, lines[index+1].indent, where)
		if err != nil {
			return nil, 0, err
		}
		mapping.Set(key, value)
		index = next
	}
	if index < len(lines) && lines[index].indent > indent {
		return nil, 0, fmt.Errorf("%s:%d: indented deeper than the keys above it", where, lines[index].number)
	}
	return mapping, index, nil
}

// FrontData reads front matter text, without its `---` lines, as data in the YAML subset; first is
// its first line's number in the file.
func FrontData(text, where string, first int) (Object, error) {
	lines, err := yamlLines(text, where, first)
	if err != nil {
		return nil, err
	}
	if len(lines) == 0 {
		return Object{}, nil
	}
	data, index, err := yamlBlock(lines, 0, 0, where)
	if err != nil {
		return nil, err
	}
	obj, ok := data.(Object)
	if !ok {
		return nil, fmt.Errorf("%s:%d: the front matter is a list; write `key: value` lines", where, lines[0].number)
	}
	if index < len(lines) {
		return nil, fmt.Errorf("%s:%d: %s is outside the front matter's keys", where, lines[index].number, lines[index].text)
	}
	return obj, nil
}
