package rules

import (
	"go/scanner"
	"go/token"
	"path"
	"regexp"
	"strconv"
	"strings"
)

// #261 moved skills into agents and left prompts naming the old files; a box
// that reads one runs a stale procedure (#363). This rule holds every plugin
// path the code, the agents, the skills and the spec name to a file of the
// checkout. Test files are fixtures, free to name a file of their own folder.
func init() {
	register(Rule{
		Name: "plugin-path",
		Doc: "a path under " + skillsDir + " or " + AgentsDir + " named in a Go string outside tests, an agent, a skill or spec/ " +
			"names a file or folder of the checkout",
		Applies: namesPlugin,
		Check:   pluginPath,
	})
}

// pluginPathRe is a path under the plugin's skills or agents. The folders are
// spelled in halves so this file names neither as a path.
var pluginPathRe = regexp.MustCompile(`src/plugin/(?:` + "skil" + `ls|` + "age" + `nts)/[A-Za-z0-9_./-]*`)

func namesPlugin(p string) bool {
	switch {
	case strings.HasPrefix(p, "spec/"):
		return true
	case strings.HasPrefix(p, AgentsDir+"/"), strings.HasPrefix(p, skillsDir+"/"):
		return path.Ext(p) == ".md"
	case path.Ext(p) == ".go":
		return !strings.HasSuffix(p, "_test.go") && !strings.Contains("/"+p, "/testdata/")
	}
	return false
}

func pluginPath(repo *Repo, p string, text []byte) []Finding {
	var found []Finding
	look := func(line int, s string) {
		for _, m := range pluginPathRe.FindAllStringIndex(s, -1) {
			if m[1] < len(s) && strings.ContainsRune("<{*$%", rune(s[m[1]])) {
				continue // a placeholder or a pattern: no one path
			}
			q := strings.TrimRight(s[m[0]:m[1]], "./")
			if !repo.Exists(q) {
				found = append(found, Finding{Path: p, Line: line, Rule: "plugin-path", Message: "no such file: " + q})
			}
		}
	}
	if path.Ext(p) != ".go" {
		for i, line := range strings.Split(string(text), "\n") {
			look(i+1, line)
		}
		return found
	}
	for _, s := range goStrings(text) {
		look(s.line, s.text)
	}
	return found
}

// goStrings answers the string literals of a Go file, each unquoted, with its
// line: a raw string's lines each with its own.
func goStrings(text []byte) []snippet {
	fset := token.NewFileSet()
	file := fset.AddFile("", fset.Base(), len(text))
	var s scanner.Scanner
	s.Init(file, text, nil, 0)
	var out []snippet
	for {
		pos, tok, lit := s.Scan()
		if tok == token.EOF {
			return out
		}
		if tok != token.STRING {
			continue
		}
		raw := strings.HasPrefix(lit, "`")
		if u, err := strconv.Unquote(lit); err == nil {
			lit = u
		}
		start := fset.Position(pos).Line
		if !raw {
			out = append(out, snippet{line: start, text: lit})
			continue
		}
		for i, l := range strings.Split(lit, "\n") {
			out = append(out, snippet{line: start + i, text: l})
		}
	}
}
