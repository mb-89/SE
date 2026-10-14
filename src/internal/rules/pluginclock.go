package rules

import (
	"bytes"
	"path"
	"regexp"
	"strings"
)

// wallClock is how plugin code reads the wall clock past $.clock: Date.now,
// called or passed, and a Date built with no argument, which is now.
var wallClock = regexp.MustCompile(`\bDate\s*\.\s*now\b|\bnew\s+Date\b\s*(\(\s*\)|[^\s(]|$)`)

// script is the files of the plugin the clock rule reads.
var script = map[string]bool{".ts": true, ".tsx": true, ".js": true, ".mjs": true}

func init() {
	register(Rule{
		Name: "plugin-clock",
		Doc:  "under src/plugin, no hook or helper reads the wall clock through Date.now() or new Date() without an argument; it asks $.clock (tests aside, which drive the mock clock)",
		Applies: func(p string) bool {
			return strings.HasPrefix(p, "src/plugin/") && !strings.HasPrefix(p, "src/plugin/tests/") &&
				!strings.Contains(path.Base(p), ".test.") && script[path.Ext(p)]
		},
		Check: pluginClock,
	})
}

func pluginClock(_ *Repo, p string, text []byte) []Finding {
	var found []Finding
	for i, line := range bytes.Split(text, []byte("\n")) {
		code := line
		if at := bytes.Index(code, []byte("//")); at >= 0 {
			code = code[:at]
		}
		if t := bytes.TrimSpace(code); bytes.HasPrefix(t, []byte("*")) || bytes.HasPrefix(t, []byte("/*")) {
			continue
		}
		if wallClock.Match(code) {
			found = append(found, Finding{Path: p, Line: i + 1, Rule: "plugin-clock", Message: "it reads the wall clock past $.clock; ask await $.clock.now()"})
		}
	}
	return found
}
