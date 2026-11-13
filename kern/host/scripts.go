package host

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// Counting an agent's ad hoc scripts, SE's docs/go-core.md "Scripts are ad
// hoc, components are long-term": on a PostToolUse of a shell tool the core
// reads the command, finds the scripts it runs and counts each run of one
// that git does not track, or that lives in a scratch or ad hoc place, into
// the use log beside the ad hoc components' calls. It counts only: the record
// names the script's path and content hash, never its arguments or output.
//
// The parsing is conservative: only a script named by its path, run directly
// (`./x.sh`, `/tmp/x.py`) or by an interpreter (`python x.py`, `bash x.sh`,
// `uv run x.py`, `node x.js`, `go run x.go`), is a candidate; an ordinary
// command (`git`, `uv run pytest`) names no path and is never one, and a
// tracked script (SE's own) or one outside the checkout and the scratch places
// is never counted.

// ShellTools are the tool names whose PostToolUse carries a shell command.
var ShellTools = map[string]bool{"Bash": true, "bash": true, "PowerShell": true, "powershell": true}

// scriptRun is one record of a script's run in the use log: when it was
// heard, the session, the script's path (under the checkout, or under a
// scratch place's marker) and the sha256 of its content.
type scriptRun struct {
	At      string `json:"at"`
	Session string `json:"session"`
	Script  string `json:"script"`
	Hash    string `json:"hash"`
}

// shellUse is the part of a PostToolUse payload the counter reads.
type shellUse struct {
	Session string `json:"session_id"`
	Cwd     string `json:"cwd"`
	Tool    string `json:"tool_name"`
	Input   struct {
		Command string `json:"command"`
	} `json:"tool_input"`
}

// countScripts records each counted script run of a PostToolUse payload
// under root; everything that fails is dropped, as counting is advice
// (recordUse).
func countScripts(root string, payload []byte, at time.Time) {
	var use shellUse
	if json.Unmarshal(payload, &use) != nil || !ShellTools[use.Tool] || use.Input.Command == "" {
		return
	}
	dir := use.Cwd
	if dir == "" {
		dir = root
	}
	for _, path := range ScriptsRun(use.Input.Command, dir) {
		key, ok := adHocScript(root, path)
		if !ok {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		sum := sha256.Sum256(data)
		appendRecord(root, scriptRun{At: at.UTC().Format(time.RFC3339), Session: use.Session,
			Script: key, Hash: hex.EncodeToString(sum[:])})
	}
}

// interpreters run the script their first argument that is no option names.
var interpreters = map[string]bool{
	"python": true, "python3": true, "py": true, "bash": true, "sh": true, "zsh": true,
	"node": true, "ruby": true, "perl": true, "pwsh": true, "powershell": true,
}

// interpreterStops are the options after which an interpreter runs no script
// file: a module, an inline program.
var interpreterStops = map[string]bool{"-m": true, "-c": true, "-e": true, "-Command": true, "-command": true}

// uvValued are uv run's options that take a value as the next word.
var uvValued = map[string]bool{
	"--with": true, "-w": true, "--python": true, "-p": true, "--project": true, "--directory": true,
	"--package": true, "--extra": true, "--group": true, "--env-file": true, "--with-requirements": true,
	"--with-editable": true, "--index": true, "--default-index": true, "--only-group": true,
}

// ScriptsRun answers the absolute paths of the script files command runs,
// read conservatively from its simple commands, each resolved against the
// directory a `cd` before it left, starting at dir. A word with an expansion
// or a substitution is never a path.
func ScriptsRun(command, dir string) []string {
	var found []string
	for _, words := range simpleCommands(command) {
		words = strip(words)
		if len(words) == 0 {
			continue
		}
		if words[0] == "cd" {
			if len(words) == 2 && plain(words[1]) {
				dir = resolve(dir, words[1])
			}
			continue
		}
		if p := scriptOf(words); p != "" {
			found = append(found, resolve(dir, p))
		}
	}
	return found
}

// strip drops a simple command's leading variable assignments and the words
// that only run the rest (`env`, `exec`, `time`, `nohup`).
func strip(words []string) []string {
	for len(words) > 0 {
		w := words[0]
		switch {
		case w == "env" || w == "exec" || w == "time" || w == "nohup" || w == "command":
			words = words[1:]
		case strings.Contains(w, "=") && !strings.HasPrefix(w, "=") && !strings.ContainsAny(w[:strings.Index(w, "=")], "/-."):
			words = words[1:]
		default:
			return words
		}
	}
	return words
}

// scriptOf is the script path a simple command's words run, or "".
func scriptOf(words []string) string {
	head := words[0]
	base := strings.TrimSuffix(filepath.Base(filepath.FromSlash(head)), ".exe")
	switch {
	case base == "uv" && len(words) > 1 && words[1] == "run":
		rest := words[2:]
		for len(rest) > 0 && strings.HasPrefix(rest[0], "-") {
			if uvValued[rest[0]] && len(rest) > 1 {
				rest = rest[1:]
			}
			rest = rest[1:]
		}
		if len(rest) == 0 {
			return ""
		}
		if p := scriptOf(rest); p != "" {
			return p
		}
		if pathLike(rest[0]) || scriptExt(rest[0]) {
			return rest[0] // uv run x.py runs the script
		}
		return ""
	case base == "go" && len(words) > 2 && words[1] == "run":
		for _, w := range words[2:] {
			if strings.HasSuffix(w, ".go") && plain(w) {
				return w
			}
			if !strings.HasPrefix(w, "-") {
				return ""
			}
		}
		return ""
	case interpreters[base] || strings.HasPrefix(base, "python3."):
		for i := 1; i < len(words); i++ {
			w := words[i]
			if interpreterStops[w] {
				return ""
			}
			if strings.HasPrefix(w, "-") {
				if w == "-File" || w == "-file" {
					if i+1 < len(words) && plain(words[i+1]) {
						return words[i+1]
					}
					return ""
				}
				continue
			}
			if plain(w) {
				return w
			}
			return ""
		}
		return ""
	case pathLike(head):
		return head
	}
	return ""
}

// pathLike says whether a word names a file by a path: it holds a separator.
func pathLike(w string) bool {
	return plain(w) && (strings.Contains(w, "/") || strings.Contains(w, `\`))
}

// scriptExt says whether a word names a script file by its extension.
func scriptExt(w string) bool {
	switch strings.ToLower(filepath.Ext(w)) {
	case ".py", ".sh", ".ps1", ".js", ".mjs", ".ts", ".rb", ".pl":
		return plain(w)
	}
	return false
}

// plain says whether a word is literal: no expansion, substitution or glob.
func plain(w string) bool {
	return w != "" && !strings.ContainsAny(w, "$`*?~<>(){}")
}

func resolve(dir, p string) string {
	p = filepath.FromSlash(p)
	if filepath.IsAbs(p) {
		return filepath.Clean(p)
	}
	return filepath.Join(dir, p)
}

// simpleCommands splits a shell command into its simple commands' words, at
// newlines, `;`, `&&`, `||`, `|` and `&`, honouring single and double quotes
// and backslash escapes.
func simpleCommands(command string) [][]string {
	var all [][]string
	var words []string
	var word strings.Builder
	inWord := false
	end := func() {
		if inWord {
			words = append(words, word.String())
			word.Reset()
			inWord = false
		}
	}
	cut := func() {
		end()
		if len(words) > 0 {
			all = append(all, words)
		}
		words = nil
	}
	rs := []rune(command)
	for i := 0; i < len(rs); i++ {
		r := rs[i]
		switch {
		case r == '\'':
			inWord = true
			j := i + 1
			for j < len(rs) && rs[j] != '\'' {
				word.WriteRune(rs[j])
				j++
			}
			i = j
		case r == '"':
			inWord = true
			j := i + 1
			for j < len(rs) && rs[j] != '"' {
				if rs[j] == '\\' && j+1 < len(rs) {
					j++
				}
				word.WriteRune(rs[j])
				j++
			}
			i = j
		case r == '\\' && i+1 < len(rs):
			if rs[i+1] == '\n' {
				i++ // a line continued
				continue
			}
			inWord = true
			i++
			word.WriteRune(rs[i])
		case r == '\n' || r == ';' || r == '|' || r == '&':
			cut()
		case r == ' ' || r == '\t' || r == '\r':
			end()
		case r == '#' && !inWord:
			for i < len(rs) && rs[i] != '\n' {
				i++
			}
			cut()
		default:
			inWord = true
			word.WriteRune(r)
		}
	}
	cut()
	return all
}

// gitWait bounds the one git call that says whether a script is tracked.
const gitWait = 2 * time.Second

// adHocScript says whether the script at path is an ad hoc one, and the key
// it is counted under: a regular file under the checkout that git neither
// tracks nor ignores, or one under the ad hoc components' folder, by its path
// under the checkout; else one in a scratch place (the system's temporary
// folder, a folder named scratchpad), by its path under that place's marker.
// Anything else, SE's own scripts and the system's among them, is not.
func adHocScript(root, path string) (string, bool) {
	st, err := os.Stat(path)
	if err != nil || !st.Mode().IsRegular() {
		return "", false
	}
	if rel, ok := under(root, path); ok {
		slash := filepath.ToSlash(rel)
		if strings.HasPrefix(slash, filepath.ToSlash(AdHocDir)+"/") {
			return slash, true
		}
		if untracked, known := gitUntracked(root, rel); known {
			return slash, untracked
		}
	}
	if i := strings.LastIndex(filepath.ToSlash(path), "/scratchpad/"); i >= 0 {
		return "<scratchpad>" + filepath.ToSlash(path)[i+len("/scratchpad"):], true
	}
	if rel, ok := under(os.TempDir(), path); ok {
		return "<tmp>/" + filepath.ToSlash(rel), true
	}
	return "", false
}

// under answers path relative to base where it lies below it.
func under(base, path string) (string, bool) {
	if base == "" {
		return "", false
	}
	if b, err := filepath.EvalSymlinks(base); err == nil {
		base = b
	}
	if p, err := filepath.EvalSymlinks(path); err == nil {
		path = p
	}
	rel, err := filepath.Rel(base, path)
	if err != nil || rel == "." || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", false
	}
	return rel, true
}

// gitUntracked says whether git in root neither tracks nor ignores rel; known
// is false where git cannot say (no repository, no git).
func gitUntracked(root, rel string) (untracked, known bool) {
	ctx, cancel := context.WithTimeout(context.Background(), gitWait)
	defer cancel()
	cmd := exec.CommandContext(ctx, "git", "-C", root, "ls-files", "--others", "--exclude-standard",
		"--", filepath.ToSlash(rel))
	out, err := cmd.Output()
	if err != nil {
		return false, false
	}
	return len(bytes.TrimSpace(out)) > 0, true
}
