package shape

import (
	"errors"
	"path/filepath"
	"strings"

	"github.com/mb-89/SE/src/internal/gitpaths"
	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// ScriptsDir is where ad hoc scripts live, relative to a checkout.
const ScriptsDir = "src/scripts"

// logFormat cuts git log into one record per change: its hash, its time and
// its subject, then the files it touched.
const logFormat = "--format=\x1e%H\x1f%ct\x1f%s"

// Read reads what Find needs from the checkout dir: every Go file under src
// (testdata left out), the scripts, the module's path, what deadcode reaches
// in production alone, the tracked files and the history of main. A missing
// deadcode is said, not failed on: the facts are advice.
func Read(d disk.Disk, p proc.Procs, dir string) (Input, error) {
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
	if err != nil {
		in.Deadcode, in.Unrun = "", err.Error()
		if errors.Is(err, proc.ErrNotFound) {
			in.Unrun = "deadcode is not installed: sh tests/tools.sh install installs it"
		}
	}
	if in.Tracked, err = gitpaths.Tracked(p, dir, false); err != nil {
		return Input{}, err
	}
	if in.Log, err = proc.Output(p, proc.Cmd{Name: "git", Args: []string{"log", "--first-parent", "-m", "--name-only", logFormat, "HEAD"}, Dir: dir}); err != nil {
		return Input{}, err
	}
	return in, nil
}
