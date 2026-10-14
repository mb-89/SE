package rules

import (
	"fmt"
	"regexp"
	"strings"
)

func init() {
	register(Rule{
		Name:    "se-command",
		Doc:     "every se command, and every flag of it, that prose names in its code exists in se's command registry",
		Applies: isProse,
		Check:   seCommand,
	})
}

// word is a token that may be a command's word; anything else (a
// placeholder, an ellipsis, a path) ends what the rule can tell.
var word = regexp.MustCompile(`^[a-z][a-z-]*$`)

// global are the flags se takes before a command's name, and whether each takes a value.
var global = map[string]bool{"session": false, "trace": false, "workspace": true, "help": false, "h": false}

// isSe says whether a token calls se: se, /se, <se>, or a path ending in /se.
func isSe(tok string) bool {
	return tok == "se" || tok == "<se>" || (strings.HasSuffix(tok, "/se") && !strings.Contains(tok, "://"))
}

func seCommand(repo *Repo, p string, text []byte) []Finding {
	var found []Finding
	for _, c := range codeOf(text) {
		toks := strings.Fields(c.text)
		for i, tok := range toks {
			if !isSe(tok) {
				continue
			}
			if msg := checkCall(repo, call(toks[i+1:])); msg != "" {
				found = append(found, Finding{Path: p, Line: c.line, Rule: "se-command", Message: msg})
			}
		}
	}
	return found
}

// call answers the tokens of one se call: up to the end of its command line.
func call(toks []string) []string {
	for i, t := range toks {
		if t == "&&" || t == "||" || t == ";" || t == "|" || isSe(t) {
			return toks[:i]
		}
	}
	return toks
}

// flagName answers the flag a token names, or "" where it names none.
func flagName(tok string) string {
	tok = strings.TrimLeft(tok, "[(")
	if !strings.HasPrefix(tok, "-") || tok == "-" || tok == "--" {
		return ""
	}
	name := strings.TrimLeft(tok, "-")
	name, _, _ = strings.Cut(name, "=")
	return strings.TrimRight(name, "])|,.;:")
}

// checkCall answers what is wrong with one se call, or "".
func checkCall(repo *Repo, toks []string) string {
	for len(toks) > 0 && flagName(toks[0]) != "" {
		f := flagName(toks[0])
		value, ok := global[f]
		if !ok {
			return fmt.Sprintf("se takes no flag --%s before a command", f)
		}
		toks = toks[1:]
		if value && len(toks) > 0 {
			toks = toks[1:]
		}
	}
	if len(toks) == 0 || !word.MatchString(toks[0]) {
		return ""
	}
	name, rest := toks[0], toks[1:]
	if len(rest) > 0 {
		if _, ok := repo.Commands[name+" "+rest[0]]; ok {
			name, rest = name+" "+rest[0], rest[1:]
		}
	}
	flags, ok := repo.Commands[name]
	if !ok {
		if !hasSubWords(repo, name) {
			return fmt.Sprintf("se has no command %q", name)
		}
		if len(rest) > 0 && word.MatchString(rest[0]) {
			return fmt.Sprintf("se has no command %q", name+" "+rest[0])
		}
		return ""
	}
	for _, t := range rest {
		f := flagName(t)
		if f == "" || f == "workspace" || f == "help" || f == "h" {
			continue
		}
		if !contains(flags, f) {
			return fmt.Sprintf("se %s takes no flag --%s", name, f)
		}
	}
	return ""
}

func hasSubWords(repo *Repo, first string) bool {
	for name := range repo.Commands {
		if strings.HasPrefix(name, first+" ") {
			return true
		}
	}
	return false
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}
