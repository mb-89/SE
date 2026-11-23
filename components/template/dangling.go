package template

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

// The rule dangling: an SE command, or a script of SE's, that a text names and that does not exist.
// The Go port of scripts/references.py `dangling` as the template engine calls it (`paths=False`,
// `created=True`): the commands of code spans and fenced blocks, checked against the command trees
// Go reads from SE's scripts (CommandTree), and a `scripts/…` path in code against SE's checkout.

// DanglingFinding is one reference that names nothing: its line in the text, the item and why.
type DanglingFinding struct {
	Line   int
	Item   string
	Reason string
}

func (f DanglingFinding) String() string {
	return fmt.Sprintf("line %d: `%s` %s", f.Line, f.Item, f.Reason)
}

var (
	pathRoots       = []string{"scripts/", "src/", "tests/", ".github/"}
	pathPlaceholder = regexp.MustCompile(`[<>*…{}$?\[\]|]`)
	codeFence       = regexp.MustCompile("^[ \t]*(`{3,}|~{3,})")
	subcommandWord  = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)
	anchorOrLine    = regexp.MustCompile(`(#.*|:\p{Nd}+(:\p{Nd}+)?)$`)
	requirementHead = regexp.MustCompile(`^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$`)
	requirementItem = regexp.MustCompile(`^[ \t]*(?:\p{Nd}+[.)]|[-*+])[ \t]+`)
	creatingWords   = []string{"new", "adds", "add", "added", "creates", "create", "created", "introduces", "introduce"}
)

const trailing = ".,;:)'\""

// Dangling is the commands (and, with bareScripts, the bare `scripts/…` paths) of text that name
// nothing in SE's checkout at seRoot, in text order, but those its Requirements say it creates.
func Dangling(text, seRoot string, bareScripts bool) []DanglingFinding {
	scripts := filepath.Join(seRoot, "scripts")
	var found []DanglingFinding
	for _, piece := range codeOf(text) {
		var tokens []codeToken
		for _, span := range fieldSpans(piece.text) {
			tokens = append(tokens, codeToken{piece.text[span[0]:span[1]], strings.Count(text[:piece.start+span[0]], "\n") + 1})
		}
		found = append(found, deadCode(tokens, seRoot, scripts, bareScripts)...)
	}
	made := requirements(text)
	var kept []DanglingFinding
	for _, f := range found {
		if !creates(made, f.Item) {
			kept = append(kept, f)
		}
	}
	sort.SliceStable(kept, func(i, j int) bool { return kept[i].Line < kept[j].Line })
	return kept
}

type codePiece struct {
	start int
	text  string
}

type codeToken struct {
	text string
	line int
}

// fieldSpans are the spans of Python's `\S+` in text.
func fieldSpans(text string) [][2]int {
	var spans [][2]int
	start := -1
	for i, r := range text {
		if isSpace(r) {
			if start >= 0 {
				spans = append(spans, [2]int{start, i})
				start = -1
			}
		} else if start < 0 {
			start = i
		}
	}
	if start >= 0 {
		spans = append(spans, [2]int{start, len(text)})
	}
	return spans
}

// codeOf is references.py `split_code`'s code: each fenced block's lines and each code span, with
// the offset it starts at, in offset order.
func codeOf(text string) []codePiece {
	var code []codePiece
	offset, fence := 0, ""
	inFence := false
	var outside [][2]int
	for _, line := range splitLines(text, true) {
		marker := codeFence.FindStringSubmatch(line)
		switch {
		case !inFence && marker != nil:
			fence, inFence = marker[1], true
		case inFence && marker != nil && strings.HasPrefix(marker[1], fence):
			inFence = false
		case inFence:
			code = append(code, codePiece{offset, strings.TrimRight(line, "\r\n")})
		default:
			outside = append(outside, [2]int{offset, offset + len(line)})
		}
		offset += len(line)
	}
	for _, run := range mergedRuns(outside) {
		code = append(code, codeSpans(text, run[0], run[1])...)
	}
	sort.SliceStable(code, func(i, j int) bool {
		if code[i].start != code[j].start {
			return code[i].start < code[j].start
		}
		return code[i].text < code[j].text
	})
	return code
}

func mergedRuns(spans [][2]int) [][2]int {
	var merged [][2]int
	for _, span := range spans {
		if len(merged) > 0 && merged[len(merged)-1][1] == span[0] {
			merged[len(merged)-1][1] = span[1]
		} else {
			merged = append(merged, span)
		}
	}
	return merged
}

// codeSpans are references.py CODE_SPAN's matches in text[begin:end], `(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)`
// with DOTALL: a run of backticks, at least one character, then a run as long, neither run beside
// another backtick; what lies before begin counts for the first look behind, as for Python's pos.
func codeSpans(text string, begin, end int) []codePiece {
	var found []codePiece
	tick := func(i int) bool { return i >= 0 && i < end && text[i] == '`' }
	for i := begin; i < end; {
		if text[i] != '`' || (i > 0 && text[i-1] == '`') {
			_, size := utf8.DecodeRuneInString(text[i:end])
			i += size
			continue
		}
		j := i
		for tick(j) {
			j++
		}
		n := j - i
		_, first := utf8.DecodeRuneInString(text[j:end])
		matched := false
		if j < end {
			for k := j + first; k+n <= end; {
				run := true
				for at := k; at < k+n; at++ {
					if text[at] != '`' {
						run = false
						break
					}
				}
				if run && text[k-1] != '`' && !tick(k+n) {
					found = append(found, codePiece{j, text[j:k]})
					i, matched = k+n, true
					break
				}
				_, size := utf8.DecodeRuneInString(text[k:end])
				k += size
			}
		}
		if !matched {
			i = j
		}
	}
	return found
}

// deadCode is references.py `dead_code` with `paths` false: a `scripts/…` path (bare only with
// bareScripts) to a file that does not exist, and a script's subcommand its parser does not define.
func deadCode(tokens []codeToken, root, scripts string, bareScripts bool) []DanglingFinding {
	var found []DanglingFinding
	for index, raw := range tokens {
		token := strings.TrimLeft(strings.TrimRight(raw.text, trailing), "('\"")
		path, ok := repositoryPath(token)
		script := ok && strings.HasPrefix(path, "scripts/") && (bareScripts || strings.HasPrefix(token, "<se>/"))
		if ok && script {
			if !pathPlaceholder.MatchString(path) {
				if _, err := os.Stat(filepath.Join(root, filepath.FromSlash(path))); err != nil {
					found = append(found, DanglingFinding{raw.line, path, "names a file that does not exist"})
					continue
				}
			}
		}
		if strings.HasSuffix(token, ".py") {
			var following []string
			for _, word := range tokens[index+1:] {
				following = append(following, word.text)
			}
			if f, ok := unknownSubcommand(pathName(token), following, scripts, raw.line); ok {
				found = append(found, f)
			}
		}
	}
	return found
}

// pathName is Python's Path(token).name: its last part.
func pathName(token string) string {
	parts := strings.Split(token, "/")
	for i := len(parts) - 1; i >= 0; i-- {
		if parts[i] != "" && parts[i] != "." {
			return parts[i]
		}
	}
	return ""
}

// repositoryPath is references.py `repository_path`: the repository path a code token names.
func repositoryPath(token string) (string, bool) {
	token = strings.TrimPrefix(token, "<se>/")
	token = strings.TrimPrefix(token, "./")
	rooted := false
	for _, prefix := range pathRoots {
		if token == prefix {
			return "", false
		}
		if strings.HasPrefix(token, prefix) {
			rooted = true
		}
	}
	if !rooted {
		return "", false
	}
	path := anchorOrLine.ReplaceAllString(token, "")
	return path, path != ""
}

func unknownSubcommand(script string, rest []string, scripts string, line int) (DanglingFinding, bool) {
	tree := CommandTree(filepath.Join(scripts, script))
	var words []string
	for _, raw := range rest {
		word := strings.TrimRight(raw, trailing)
		if len(tree) == 0 || !subcommandWord.MatchString(word) {
			return DanglingFinding{}, false
		}
		words = append(words, word)
		next, ok := tree[word]
		if !ok {
			return DanglingFinding{line, strings.Join(append([]string{script}, words...), " "),
				fmt.Sprintf("names a subcommand %s's parser does not define; it defines %s", script, joinStrings(tree.Names()))}, true
		}
		tree = next
	}
	return DanglingFinding{}, false
}

// requirements is references.py `requirements`: the items of the text's Requirements sections,
// each with its continuation lines.
func requirements(text string) []string {
	var items []string
	level := 0
	for _, line := range splitLines(text, false) {
		if m := requirementHead.FindStringSubmatch(line); m != nil {
			depth := len(m[1])
			if level > 0 && depth <= level {
				level = 0
			}
			if level == 0 && strings.ToLower(strip(m[2])) == "requirements" {
				level = depth
			}
			continue
		}
		if level == 0 {
			continue
		}
		if requirementItem.MatchString(line) || len(items) == 0 {
			items = append(items, line)
		} else if strip(line) != "" {
			items[len(items)-1] += " " + strip(line)
		}
	}
	return items
}

// creates is references.py `creates`: whether one requirement names the reference (each of its
// words, a path by its file name) and says it is new, added or created.
func creates(items []string, reference string) bool {
	var named []string
	for _, word := range words(reference) {
		if strings.Contains(word, "/") {
			word = pathName(word)
		}
		named = append(named, word)
	}
	for _, item := range items {
		if !saysCreating(item) {
			continue
		}
		all := true
		for _, word := range named {
			if !strings.Contains(item, word) {
				all = false
				break
			}
		}
		if all {
			return true
		}
	}
	return false
}

// saysCreating is references.py CREATING's search: `\b(new|adds?|added|creates?|created|introduces?)\b`,
// ignoring case, its word boundaries Python's.
func saysCreating(text string) bool {
	runes := []rune(text)
	for i := range runes {
		if !isWordRune(runes[i]) || (i > 0 && isWordRune(runes[i-1])) {
			continue
		}
		for _, word := range creatingWords {
			w := []rune(word)
			if i+len(w) > len(runes) || (i+len(w) < len(runes) && isWordRune(runes[i+len(w)])) {
				continue
			}
			if strings.EqualFold(string(runes[i:i+len(w)]), word) {
				return true
			}
		}
	}
	return false
}

// fieldAt is templates.py `_field_at`: the field whose section holds a line of the document's text.
func fieldAt(doc *Document, line int) string {
	count := 1
	for _, part := range doc.Parts {
		if part.Kind == "prefix" || part.Kind == "gap" || part.Kind == "suffix" {
			continue
		}
		lines := part.Raw
		if part.Heading != "" {
			lines = part.Heading + "\n" + part.Raw
		}
		if part.Kind == "scope" {
			lines = part.Heading + "\n"
		}
		size := strings.Count(lines, "\n")
		if count <= line && line < count+size {
			if part.Kind == "field" {
				return part.Name
			}
			return "body"
		}
		count += size
	}
	return "body"
}
