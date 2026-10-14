package rules

import (
	"bytes"
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/printer"
	"go/token"
	"path"
	"regexp"
	"strconv"
	"strings"
)

// A command's help written as one long string literal is one line every
// change to the command touches, so two changes to it conflict (#495). Its
// Details are a list of sentences, joined at print, and merge per sentence.
func init() {
	register(Rule{
		Name: "help-sentences",
		Doc: "a Go string literal under a Details or Help key holds one sentence, and a command's Details are a list of them, " +
			"so two changes to its help merge per sentence",
		Applies: func(p string) bool { return path.Ext(p) == ".go" },
		Check:   helpSentences,
		Fix:     splitHelp,
	})
}

// helpKeys are the keys whose string literals are help text.
var helpKeys = map[string]bool{"Details": true, "Help": true}

// abbreviation is a word whose stop ends no sentence: e.g., i.e.
var abbreviation = regexp.MustCompile(`^[("']*[a-zA-Z](\.[a-zA-Z])+\.$`)

// sentences answers a text cut into its sentences, the spaces between them
// dropped. A sentence ends at a stop (not an ellipsis's, nor an
// abbreviation's), with any closing quote or bracket, then a space and more text.
func sentences(text string) []string {
	var out []string
	start := 0
	for i := 0; i < len(text); i++ {
		if !strings.ContainsRune(".!?", rune(text[i])) || (i > 0 && text[i-1] == '.') || (i+1 < len(text) && text[i+1] == '.') ||
			abbreviation.MatchString(text[strings.LastIndexByte(text[:i], ' ')+1:i+1]) {
			continue
		}
		end := i + 1
		for end < len(text) && strings.ContainsRune(`"')]`, rune(text[end])) {
			end++
		}
		next := end
		for next < len(text) && text[next] == ' ' {
			next++
		}
		if next == end || next == len(text) {
			continue
		}
		out = append(out, text[start:end])
		start, i = next, next-1
	}
	return append(out, text[start:])
}

// helpValues answers the value of every Details or Help key in the file's
// composite literals.
func helpValues(f *ast.File) []*ast.KeyValueExpr {
	var kvs []*ast.KeyValueExpr
	ast.Inspect(f, func(n ast.Node) bool {
		kv, ok := n.(*ast.KeyValueExpr)
		if !ok {
			return true
		}
		if k, ok := kv.Key.(*ast.Ident); ok && helpKeys[k.Name] {
			kvs = append(kvs, kv)
		}
		return true
	})
	return kvs
}

// longLit is a string literal of more than one sentence, and how many it holds.
type longLit struct {
	lit *ast.BasicLit
	n   int
}

// long answers every string literal in e that holds more than one sentence,
// in the order they stand.
func long(e ast.Node) []longLit {
	var out []longLit
	ast.Inspect(e, func(n ast.Node) bool {
		lit, ok := n.(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			return true
		}
		if s, err := strconv.Unquote(lit.Value); err == nil {
			if n := len(sentences(s)); n > 1 {
				out = append(out, longLit{lit, n})
			}
		}
		return true
	})
	return out
}

func helpSentences(_ *Repo, p string, text []byte) []Finding {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.SkipObjectResolution)
	if err != nil {
		return nil
	}
	var found []Finding
	for _, kv := range helpValues(f) {
		key := kv.Key.(*ast.Ident).Name
		if _, list := kv.Value.(*ast.CompositeLit); key == "Details" && !list {
			found = append(found, Finding{
				Path: p, Line: fset.Position(kv.Value.Pos()).Line, Rule: "help-sentences",
				Message: "a command's Details are a list of sentences, []string{...}, not one string (se rules --fix makes it one)",
			})
		}
		for _, l := range long(kv.Value) {
			msg := fmt.Sprintf("a %s string literal holds %d sentences; write one sentence a literal", key, l.n)
			if key == "Details" {
				msg += ", the Details a list of them (se rules --fix splits it)"
			}
			found = append(found, Finding{Path: p, Line: fset.Position(l.lit.Pos()).Line, Rule: "help-sentences", Message: msg})
		}
	}
	return found
}

// splitHelp rewrites every Details value as a list of its sentences: a value
// that is no list becomes a []string, and an element of a list holding more
// than one sentence becomes its sentences in its place. A sentence
// that carries a value is a fmt.Sprintf of it. A value it cannot read it leaves.
func splitHelp(_ *Repo, p string, text []byte) ([]byte, bool) {
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, p, text, parser.ParseComments|parser.SkipObjectResolution)
	if err != nil {
		return text, false
	}
	type edit struct {
		from, to int
		with     string
	}
	var edits []edit
	replace := func(e ast.Expr, list bool) {
		parts, ok := sentencesOf(fset, text, e)
		if !ok {
			return
		}
		with := strings.Join(parts, ",\n")
		if list {
			with = "[]string{\n" + with + ",\n}"
		}
		edits = append(edits, edit{fset.Position(e.Pos()).Offset, fset.Position(e.End()).Offset, with})
	}
	for _, kv := range helpValues(f) {
		if kv.Key.(*ast.Ident).Name != "Details" {
			continue
		}
		cl, ok := kv.Value.(*ast.CompositeLit)
		if !ok {
			replace(kv.Value, true)
			continue
		}
		for _, elt := range cl.Elts {
			if len(long(elt)) > 0 {
				replace(elt, false)
			}
		}
	}
	if len(edits) == 0 {
		return text, false
	}
	out := append([]byte(nil), text...)
	for i := len(edits) - 1; i >= 0; i-- {
		e := edits[i]
		out = append(out[:e.from:e.from], append([]byte(e.with), out[e.to:]...)...)
	}
	if bytes.Contains(out, []byte("fmt.Sprintf(")) && !importsFmt(f) {
		at := fset.Position(f.Name.End()).Offset
		out = append(out[:at:at], append([]byte("\n\nimport \"fmt\""), out[at:]...)...)
	}
	formatted, err := format.Source(out)
	if err != nil {
		return text, false
	}
	return formatted, true
}

func importsFmt(f *ast.File) bool {
	for _, im := range f.Imports {
		if im.Path.Value == `"fmt"` && (im.Name == nil || im.Name.Name == "fmt") {
			return true
		}
	}
	return false
}

// sentencesOf answers e's text cut into sentences, each as Go source: a
// literal, or a fmt.Sprintf where the sentence carries a value.
func sentencesOf(fset *token.FileSet, src []byte, e ast.Expr) ([]string, bool) {
	tmpl, args, ok := template(fset, src, e)
	if !ok {
		return nil, false
	}
	var out []string
	for _, s := range sentences(tmpl) {
		n := verbs(s)
		if n == 0 {
			out = append(out, strconv.Quote(strings.ReplaceAll(s, "%%", "%")))
			continue
		}
		out = append(out, "fmt.Sprintf("+strconv.Quote(s)+", "+strings.Join(args[:n], ", ")+")")
		args = args[n:]
	}
	return out, len(args) == 0
}

// template answers e as one format string and the source of the values it
// carries, in order: a literal is its text, a fmt.Sprintf its format and
// arguments, a sum its parts, and any other value a %v.
func template(fset *token.FileSet, src []byte, e ast.Expr) (string, []string, bool) {
	switch x := e.(type) {
	case *ast.ParenExpr:
		return template(fset, src, x.X)
	case *ast.BasicLit:
		if x.Kind != token.STRING {
			break
		}
		s, err := strconv.Unquote(x.Value)
		return strings.ReplaceAll(s, "%", "%%"), nil, err == nil
	case *ast.BinaryExpr:
		if x.Op != token.ADD {
			break
		}
		l, la, ok := template(fset, src, x.X)
		if !ok {
			return "", nil, false
		}
		r, ra, ok := template(fset, src, x.Y)
		return l + r, append(la, ra...), ok
	case *ast.CallExpr:
		sel, ok := x.Fun.(*ast.SelectorExpr)
		if !ok || len(x.Args) == 0 || x.Ellipsis.IsValid() {
			break
		}
		if pkg, ok := sel.X.(*ast.Ident); !ok || pkg.Name != "fmt" || sel.Sel.Name != "Sprintf" {
			break
		}
		lit, ok := x.Args[0].(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			return "", nil, false
		}
		s, err := strconv.Unquote(lit.Value)
		if err != nil || strings.Contains(s, "%[") || verbs(s) != len(x.Args)-1 {
			return "", nil, false
		}
		var args []string
		for _, a := range x.Args[1:] {
			args = append(args, source(fset, a))
		}
		return s, args, true
	}
	return "%v", []string{source(fset, e)}, true
}

// verbs counts the formatting verbs of a format string, %% not among them.
func verbs(s string) int {
	n := 0
	for i := 0; i < len(s); i++ {
		if s[i] != '%' {
			continue
		}
		if i+1 < len(s) && s[i+1] == '%' {
			i++
			continue
		}
		n++
	}
	return n
}

func source(fset *token.FileSet, e ast.Expr) string {
	var b bytes.Buffer
	_ = printer.Fprint(&b, fset, e)
	return b.String()
}
