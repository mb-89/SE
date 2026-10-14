package rules

import (
	"bytes"
	"path"
	"strings"
)

// go.mod lives in src/ (#155), so a go command run from anywhere else finds
// no module. The rule reads the places that run go outside Go itself: the
// workflows, tests/ and the shell scripts under src/ (#276).
func init() {
	register(Rule{
		Name:    "go-in-src",
		Doc:     "a go command in .github/workflows, tests/ or src/**/*.sh runs from src/, which holds go.mod: go -C src",
		Applies: runsGo,
		Check:   goInSrc,
	})
}

func runsGo(p string) bool {
	switch {
	case strings.HasPrefix(p, ".github/workflows/"):
		return path.Ext(p) == ".yml" || path.Ext(p) == ".yaml"
	case strings.HasPrefix(p, "tests/"):
		return true
	case strings.HasPrefix(p, "src/"):
		return path.Ext(p) == ".sh"
	}
	return false
}

// goVerbs are go's commands; a "go" followed by one of them, or by a flag,
// is a go command rather than the word.
var goVerbs = map[string]bool{
	"build": true, "bug": true, "clean": true, "doc": true, "env": true, "fix": true, "fmt": true,
	"generate": true, "get": true, "install": true, "list": true, "mod": true, "work": true,
	"run": true, "telemetry": true, "test": true, "tool": true, "version": true, "vet": true,
}

func goInSrc(_ *Repo, p string, text []byte) []Finding {
	var found []Finding
	for i, line := range bytes.Split(text, []byte("\n")) {
		toks := strings.Fields(uncomment(string(line)))
		for j, tok := range toks {
			tok = strings.TrimLeft(tok, "$(`")
			if tok != "go" || j+1 >= len(toks) {
				continue
			}
			args := toks[j+1:]
			if !goVerbs[args[0]] && !strings.HasPrefix(args[0], "-") {
				continue
			}
			if inSrc(args) || moduleFree(args) {
				continue
			}
			found = append(found, Finding{Path: p, Line: i + 1, Rule: "go-in-src", Message: "go runs outside src/, which holds go.mod; write go -C src"})
		}
	}
	return found
}

// uncomment cuts a line's shell or YAML comment.
func uncomment(line string) string {
	if strings.HasPrefix(strings.TrimSpace(line), "#") {
		return ""
	}
	if i := strings.Index(line, " #"); i >= 0 {
		return line[:i]
	}
	return line
}

// inSrc says whether go's arguments start with -C naming src/: src, ./src,
// a path ending in /src, or a variable named src.
func inSrc(args []string) bool {
	if len(args) < 2 || args[0] != "-C" {
		return false
	}
	dir := strings.Trim(args[1], `"'`)
	dir = strings.TrimSuffix(dir, "/")
	switch dir {
	case "src", "./src", "$src", "${src}":
		return true
	}
	return strings.HasSuffix(dir, "/src")
}

// moduleFree says whether the go command reads no module, so it may run
// anywhere: go env, go version, go run of a pkg@version, and go install of
// packages none of which is a local path, as pkg@version is, spelled out or
// held in a variable ("$pkg").
func moduleFree(args []string) bool {
	switch args[0] {
	case "env", "version":
		return true
	case "run":
		for _, a := range args[1:] {
			if strings.Contains(strings.Trim(a, `"'`), "@") {
				return true
			}
		}
	case "install":
		pkgs := 0
		for _, a := range args[1:] {
			a = strings.Trim(a, `"'`)
			if strings.HasPrefix(a, "-") {
				continue
			}
			if a == "" || strings.HasPrefix(a, ".") || strings.HasPrefix(a, "/") {
				return false
			}
			pkgs++
		}
		return pkgs > 0
	}
	return false
}
