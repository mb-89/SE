package start

import (
	"bytes"
	"context"
	"errors"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

// Stop is the first words of the start's stop (docs/components.md "Required and optional at start").
const Stop = "SE cannot start"

// PythonVersion is the Python the start runs SE's scripts on, as bootstrap.sh's python_version.
const PythonVersion = "3.11"

// Run runs a program in dir and answers its standard output, its standard error and its exit
// code; err is set only where it could not run at all.
type Run func(ctx context.Context, dir string, argv []string) (stdout, stderr string, code int, err error)

// Program is the Run that starts the program as a child process.
func Program(ctx context.Context, dir string, argv []string) (string, string, int, error) {
	cmd := exec.CommandContext(ctx, argv[0], argv[1:]...)
	cmd.Dir = dir
	var out, errs bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errs
	err := cmd.Run()
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return out.String(), errs.String(), exit.ExitCode(), nil
	}
	if err != nil {
		return out.String(), errs.String(), -1, err
	}
	return out.String(), errs.String(), 0, nil
}

// Finder is the argv of the finder the components step runs: SE's Python one,
// `se_modules.py sync --quiet` of the SE at seRoot, until kern's `components` verb ports it
// (docs/components.md "The packages", package 1), so the step calls Python only for what Go
// lacks.
func Finder(seRoot, root string) []string {
	return []string{"uv", "run", "--no-project", "--python", ">=" + PythonVersion, "python",
		filepath.ToSlash(filepath.Join(seRoot, "scripts", "se_modules.py")), "--root", root, "sync", "--quiet"}
}

// Components is the start's components step, before the core starts (docs/components.md
// "Required and optional at start"): the tree of the project's components resolved from what is
// placed first, the rest found and placed at its pins by the finder (Finder). It answers the
// lines to show and whether the start stops: the finder's refusal is one message opening with
// Stop, as is any other failure to run it; an optional component missing is the finder's one
// line, and the start goes on. A project without an se.toml says nothing. It fails closed: SE
// works with nothing half-started.
func Components(ctx context.Context, seRoot, root string, run Run) ([]string, bool) {
	if root == "" || !isFile(filepath.Join(root, "se.toml")) {
		return nil, false
	}
	out, errs, code, err := run(ctx, root, Finder(seRoot, root))
	if err != nil {
		return []string{Stop + ": resolving the components failed: " + err.Error()}, true
	}
	if code != 0 {
		return refusal(errs, code), true
	}
	return lines(out), false
}

// refusal is the stop the finder's failure makes: its `error:` message, from that line on, else
// its last line of standard error.
func refusal(errs string, code int) []string {
	said := lines(errs)
	for i, line := range said {
		if text, ok := strings.CutPrefix(line, "error: "); ok {
			return append([]string{Stop + ": " + text}, said[i+1:]...)
		}
	}
	last := "it exited " + strconv.Itoa(code) + " without a word"
	if len(said) > 0 {
		last = said[len(said)-1]
	}
	return []string{Stop + ": resolving the components failed: " + last}
}

// lines is text's lines, its trailing empty ones dropped.
func lines(text string) []string {
	text = strings.TrimRight(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	if text == "" {
		return nil
	}
	return strings.Split(text, "\n")
}
