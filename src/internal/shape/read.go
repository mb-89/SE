package shape

import (
	"errors"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// ScriptsDir is where ad hoc scripts live, relative to a checkout.
const ScriptsDir = "src/scripts"

// logFormat cuts git log into one record per change: its hash, its time and
// its subject, then the files it touched.
const logFormat = "--format=\x1e%H\x1f%ct\x1f%s"

// ErrDeadcode is Read's refusal where deadcode cannot run: without it the
// production-unreachable fact would be empty, not absent.
var ErrDeadcode = errors.New("deadcode cannot run")

// installs installs the pinned tools that are missing, deadcode among them,
// and runs deadcode on the PATH tools.sh sets, from the checkout's root.
const installs = "sh tests/tools.sh install >&2 && . ./tests/tools.sh && cd src && exec deadcode ./..."

// Read reads what Find needs from the checkout dir: every Go file under src
// (testdata left out), the scripts, the module's path, what deadcode reaches
// in production alone, the tracked files, the history of main, and the se
// command lines in the session logs, logs being their folder in a checkout,
// this one's and, for a worktree, its main checkout's. A deadcode missing is
// installed at its pin through tests/tools.sh install; one that cannot run
// refuses the read (ErrDeadcode).
func Read(d disk.Disk, p proc.Procs, dir, logs string) (Input, error) {
	in := Input{Files: map[string][]byte{}, Scripts: map[string][]byte{}}
	mod, err := d.ReadFile(filepath.Join(dir, "src", "go.mod"))
	if err != nil {
		return Input{}, err
	}
	first, _, _ := strings.Cut(string(mod), "\n")
	in.Module = strings.TrimSpace(strings.TrimPrefix(first, "module"))
	all, err := d.Walk(filepath.Join(dir, "src"))
	if err != nil {
		return Input{}, err
	}
	for _, path := range all {
		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return Input{}, err
		}
		rel = filepath.ToSlash(rel)
		goFile := strings.HasSuffix(rel, ".go") && !strings.Contains(rel, "/testdata/")
		script := strings.HasPrefix(rel, ScriptsDir+"/") && !strings.HasSuffix(rel, "README.md")
		if !goFile && !script {
			continue
		}
		data, err := d.ReadFile(path)
		if err != nil {
			return Input{}, err
		}
		if goFile {
			in.Files[rel] = data
		} else {
			in.Scripts[rel] = data
		}
	}
	in.Deadcode, err = proc.Output(p, proc.Cmd{Name: "deadcode", Args: []string{"./..."}, Dir: filepath.Join(dir, "src")})
	if errors.Is(err, proc.ErrNotFound) {
		if in.Deadcode, err = proc.Output(p, proc.Cmd{Name: "sh", Args: []string{"-c", installs}, Dir: dir}); err != nil {
			return Input{}, fmt.Errorf("%w: it is not installed, and sh tests/tools.sh install did not install it at its pin: %v", ErrDeadcode, err)
		}
	}
	if err != nil {
		return Input{}, fmt.Errorf("%w: %v", ErrDeadcode, err)
	}
	tracked, err := proc.Output(p, proc.Cmd{Name: "git", Args: []string{"ls-files"}, Dir: dir})
	if err != nil {
		return Input{}, err
	}
	in.Tracked = strings.Split(tracked, "\n")
	if in.Log, err = proc.Output(p, proc.Cmd{Name: "git", Args: []string{"log", "--first-parent", "-m", "--name-only", logFormat, "HEAD"}, Dir: dir}); err != nil {
		return Input{}, err
	}
	folders := []string{filepath.Join(dir, logs)}
	if common, err := proc.Output(p, proc.Cmd{Name: "git", Args: []string{"rev-parse", "--path-format=absolute", "--git-common-dir"}, Dir: dir}); err == nil && filepath.Base(common) == ".git" {
		if main := filepath.Join(filepath.Dir(common), logs); main != folders[0] {
			folders = append(folders, main)
		}
	}
	for _, f := range folders {
		ran, err := logged(d, f)
		if err != nil {
			return Input{}, err
		}
		in.Ran = append(in.Ran, ran...)
	}
	return in, nil
}
