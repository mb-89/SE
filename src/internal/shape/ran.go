package shape

import (
	"encoding/json"
	"errors"
	"io/fs"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
)

// Ran is an se command line that ran, and when; At is zero where its source
// was read for the window already.
type Ran struct {
	At   time.Time
	Line string
}

// called is where an se command line starts: se as a word, or a path to it.
var called = regexp.MustCompile(`(?:^|[\s/"'(=])se\s+`)

// segments cuts a shell line into its commands.
var segments = regexp.MustCompile(`\n|&&|\|\||;|\|`)

// logged reads the se command lines from the session logs in the folder
// dir: each se.call row's words, and every command a row's event carries
// (a Bash tool call's). A folder that is missing holds none.
func logged(d disk.Disk, dir string) ([]Ran, error) {
	names, err := d.List(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []Ran
	for _, name := range names {
		if !strings.HasSuffix(name, ".jsonl") {
			continue
		}
		data, err := d.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return nil, err
		}
		for _, row := range strings.Split(string(data), "\n") {
			var r struct {
				At    string `json:"at"`
				Event string `json:"event"`
				E     any    `json:"e"`
			}
			if json.Unmarshal([]byte(row), &r) != nil {
				continue
			}
			at, err := time.Parse(time.RFC3339Nano, r.At)
			if err != nil {
				continue
			}
			if r.Event == "se.call" {
				if e, ok := r.E.(map[string]any); ok {
					if words, ok := e["words"].([]any); ok {
						line := "se"
						for _, w := range words {
							if s, ok := w.(string); ok {
								line += " " + s
							}
						}
						out = append(out, Ran{at, line})
					}
				}
				continue
			}
			for _, c := range commandsIn(r.E) {
				out = append(out, Ran{at, c})
			}
		}
	}
	return out, nil
}

// commandsIn is every string under a key "command" in an event.
func commandsIn(v any) []string {
	var out []string
	switch v := v.(type) {
	case map[string]any:
		for k, x := range v {
			if s, ok := x.(string); ok && k == "command" {
				out = append(out, s)
			} else {
				out = append(out, commandsIn(x)...)
			}
		}
	case []any:
		for _, x := range v {
			out = append(out, commandsIn(x)...)
		}
	}
	return out
}

// used reads which commands, and which of their flags, the lines ran: each
// command is the longest name that follows se in a segment of a line.
func used(lines []string, cs []Surface) map[string]map[string]bool {
	out := map[string]map[string]bool{}
	for _, line := range lines {
		for _, seg := range segments.Split(line, -1) {
			at := called.FindStringIndex(seg)
			if at == nil {
				continue
			}
			words := strings.Fields(seg[at[1]:])
			rest := " " + strings.Join(words, " ") + " "
			name := ""
			for _, c := range cs {
				if strings.HasPrefix(rest, " "+c.Name+" ") && len(c.Name) > len(name) {
					name = c.Name
				}
			}
			if name == "" {
				continue
			}
			if out[name] == nil {
				out[name] = map[string]bool{}
			}
			for _, w := range words {
				if flag, ok := strings.CutPrefix(w, "--"); ok {
					flag, _, _ = strings.Cut(flag, "=")
					out[name][flag] = true
				}
			}
		}
	}
	return out
}
