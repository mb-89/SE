// Command release builds kern's release from release.toml: the bare binary
// for linux, darwin and windows on amd64 and arm64, each archived, and a
// SHA256SUMS file over the archives (kern/README.md "Release").
//
//	go run ./tools/release plan  [--repository OWNER/NAME]   print version=, tag=, repository= and download=
//	go run ./tools/release build --out DIR                   build the six archives and SHA256SUMS into DIR
//	go run ./tools/release guard [--dir DIR]                 refuse a change to the binary's inputs since its released tag
//
// On a work branch, $SE_COMPONENT_KINDS (KindsVariable) names the release kind
// its field report states for each binary, as `se=patch,kern=minor`: there a
// changed input passes where its binary's kind is stated, as the landing
// assigns the version (SE's README "Component versions").
//
// plan refuses when --repository is given and the download URL names another
// repository, so a moved URL never publishes into the old one. guard refuses
// where the tag release.toml names is cut already and a file the binary is
// built from changed since it, so a binary input never changes without the
// version (Guard). Run from kern/.
// Exit codes: 0 done, 1 guard refused, 2 a usage, settings or build error.
package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	gitdoor "github.com/mb-89/kern/git"
	"github.com/pelletier/go-toml/v2"
)

// Settings is the file that owns kern's version and its release URL.
const Settings = "release.toml"

// DefaultBinary and DefaultPackage are the bare core's name and its package;
// an application that builds its own binary (core plus its Go components) names
// its own with `binary` and `package` in its release.toml (kern/README.md
// "Release", SE's docs/go-core.md "How the binary arrives").
const (
	DefaultBinary  = "kern"
	DefaultPackage = "./cmd/kern"
)

// Target is one platform a release carries.
type Target struct{ OS, Arch string }

// Targets are the six platforms, in the order SHA256SUMS lists them.
var Targets = []Target{
	{"darwin", "amd64"}, {"darwin", "arm64"},
	{"linux", "amd64"}, {"linux", "arm64"},
	{"windows", "amd64"}, {"windows", "arm64"},
}

// Stamp is every archive entry's time, so a rebuild of one commit gives the
// same archives and the same sums.
var Stamp = time.Date(1980, 1, 1, 0, 0, 0, 0, time.UTC)

// Release is release.toml read and resolved.
type Release struct {
	Version    string // 0.1.0
	Download   string // the download base, the version filled in
	Repository string // owner/name the download URL names
	Tag        string // the release's tag, the URL's last path part
	Binary     string // the binary's name, kern by default
	Package    string // the binary's Go package, ./cmd/kern by default
}

var (
	semver   = regexp.MustCompile(`^\d+\.\d+\.\d+$`)
	download = regexp.MustCompile(`^https://github\.com/([\w.-]+/[\w.-]+)/releases/download/([\w.-]*\{version\}[\w.-]*)$`)
	binary   = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)
)

// Read reads release.toml's text. `binary` and `package` default to the bare
// core's, so kern's own release.toml names neither.
func Read(data []byte) (Release, error) {
	var doc struct {
		Version  string `toml:"version"`
		Download string `toml:"download"`
		Binary   string `toml:"binary"`
		Package  string `toml:"package"`
	}
	if err := toml.Unmarshal(data, &doc); err != nil {
		return Release{}, fmt.Errorf("%s: %w", Settings, err)
	}
	if !semver.MatchString(doc.Version) {
		return Release{}, fmt.Errorf("%s: version %q is no <major>.<minor>.<patch>", Settings, doc.Version)
	}
	m := download.FindStringSubmatch(doc.Download)
	if m == nil {
		return Release{}, fmt.Errorf("%s: download %q is no https://github.com/<owner>/<name>/releases/download/<tag with {version}>", Settings, doc.Download)
	}
	name, pkg := doc.Binary, doc.Package
	if name == "" {
		name = DefaultBinary
	}
	if pkg == "" {
		pkg = DefaultPackage
	}
	if !binary.MatchString(name) {
		return Release{}, fmt.Errorf("%s: binary %q is no lower-case name of letters, digits and dashes", Settings, name)
	}
	return Release{
		Version:    doc.Version,
		Download:   strings.ReplaceAll(doc.Download, "{version}", doc.Version),
		Repository: m[1],
		Tag:        strings.ReplaceAll(m[2], "{version}", doc.Version),
		Binary:     name,
		Package:    pkg,
	}, nil
}

// Archive names a target's archive: <binary>-<version>-<os>-<arch>.tar.gz, .zip on Windows.
func Archive(r Release, t Target) string {
	ext := ".tar.gz"
	if t.OS == "windows" {
		ext = ".zip"
	}
	return fmt.Sprintf("%s-%s-%s-%s%s", r.Binary, r.Version, t.OS, t.Arch, ext)
}

// Executable names the binary inside a target's archive.
func Executable(r Release, t Target) string {
	if t.OS == "windows" {
		return r.Binary + ".exe"
	}
	return r.Binary
}

// Pack writes one executable into an archive at path: a gzipped tar, or a zip
// where path ends in .zip, the entry named name with mode 0755.
func Pack(path, name string, binary []byte) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	if strings.HasSuffix(path, ".zip") {
		z := zip.NewWriter(f)
		h := &zip.FileHeader{Name: name, Method: zip.Deflate, Modified: Stamp}
		h.SetMode(0o755)
		w, err := z.CreateHeader(h)
		if err == nil {
			_, err = w.Write(binary)
		}
		if err == nil {
			err = z.Close()
		}
		return errors.Join(err, f.Close())
	}
	g := gzip.NewWriter(f)
	g.ModTime = Stamp
	t := tar.NewWriter(g)
	err = t.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(binary)), ModTime: Stamp, Typeflag: tar.TypeReg, Format: tar.FormatPAX})
	if err == nil {
		_, err = t.Write(binary)
	}
	if err == nil {
		err = t.Close()
	}
	if err == nil {
		err = g.Close()
	}
	return errors.Join(err, f.Close())
}

// Sums writes SHA256SUMS into dir over the files named, sorted, in the
// format `sha256sum -c` reads: the hex sum, two spaces, the file name.
func Sums(dir string, names []string) error {
	sorted := append([]string{}, names...)
	sort.Strings(sorted)
	var b strings.Builder
	for _, name := range sorted {
		data, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return err
		}
		sum := sha256.Sum256(data)
		fmt.Fprintf(&b, "%s  %s\n", hex.EncodeToString(sum[:]), name)
	}
	return os.WriteFile(filepath.Join(dir, "SHA256SUMS"), []byte(b.String()), 0o644)
}

// Build cross-compiles the binary for every target into out, archives each
// and writes SHA256SUMS; it answers the archives' names. The go build runs in
// dir, the folder that holds release.toml and the binary's package (kern/ for
// the bare core, the application's own folder for its binary).
func Build(r Release, dir, out string, log io.Writer) ([]string, error) {
	if err := os.MkdirAll(out, 0o755); err != nil {
		return nil, err
	}
	scratch, err := os.MkdirTemp("", "kern-release-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(scratch)
	var names []string
	for _, t := range Targets {
		bin := filepath.Join(scratch, t.OS+"-"+t.Arch, Executable(r, t))
		start := time.Now()
		build := exec.Command("go", "build", "-trimpath", "-ldflags=-s -w", "-o", bin, r.Package)
		build.Dir = dir
		build.Env = append(os.Environ(), "GOOS="+t.OS, "GOARCH="+t.Arch, "CGO_ENABLED=0")
		build.Stdout, build.Stderr = log, log
		if err := build.Run(); err != nil {
			return nil, fmt.Errorf("go build for %s/%s: %w", t.OS, t.Arch, err)
		}
		data, err := os.ReadFile(bin)
		if err != nil {
			return nil, err
		}
		name := Archive(r, t)
		if err := Pack(filepath.Join(out, name), Executable(r, t), data); err != nil {
			return nil, fmt.Errorf("archive %s: %w", name, err)
		}
		st, err := os.Stat(filepath.Join(out, name))
		if err != nil {
			return nil, err
		}
		fmt.Fprintf(log, "release: %s, binary %.1f MB, archive %.1f MB, built in %.1f s\n",
			name, float64(len(data))/1e6, float64(st.Size())/1e6, time.Since(start).Seconds())
		names = append(names, name)
	}
	return names, Sums(out, names)
}

// Inputs answers the files, by their path in the repository as git writes it,
// that the binary in dir is built from: every non-standard package its package
// imports, the package itself among them (each package's files but its tests,
// its embedded files) and the go.mod and go.sum of each module those packages
// come from, kern's through the application's replace among them. A file
// listed is an input; a package folder is too, so a file added or deleted in
// one counts.
func Inputs(r Release, dir string) (folders, files map[string]bool, err error) {
	prefix, err := git(dir, "rev-parse", "--show-prefix")
	if err != nil {
		return nil, nil, err
	}
	main, err := goList(dir, "-m")
	if err != nil {
		return nil, nil, err
	}
	if len(main) != 1 {
		return nil, nil, fmt.Errorf("go list -m in %s answers %d main modules", dir, len(main))
	}
	// A path in the repository: go list's absolute path made relative to the
	// main module's folder, as go list writes both, then under dir's prefix.
	inRepo := func(p string) (string, bool) {
		rel, err := filepath.Rel(main[0].Dir, p)
		if err != nil {
			return "", false
		}
		full := path.Clean(path.Join(strings.TrimSpace(prefix), filepath.ToSlash(rel)))
		return full, full != ".." && !strings.HasPrefix(full, "../")
	}
	pkgs, err := goList(dir, "-deps", r.Package)
	if err != nil {
		return nil, nil, err
	}
	folders, files = map[string]bool{}, map[string]bool{}
	for _, p := range pkgs {
		if p.Standard {
			continue
		}
		if f, ok := inRepo(p.Dir); ok {
			folders[f] = true
			for _, name := range append(append([]string{}, p.GoFiles...), p.EmbedFiles...) {
				files[path.Join(f, filepath.ToSlash(name))] = true
			}
		}
		if p.Module != nil && p.Module.Dir != "" {
			if m, ok := inRepo(p.Module.Dir); ok {
				files[path.Join(m, "go.mod")], files[path.Join(m, "go.sum")] = true, true
			}
		}
	}
	return folders, files, nil
}

// Input says whether a changed file, by its path in the repository, is one of
// the binary's inputs: a file listed, or any file in a package folder but its
// tests and its prose.
func Input(folders, files map[string]bool, name string) bool {
	if files[name] {
		return true
	}
	if !folders[path.Dir(name)] {
		return false
	}
	return !strings.HasSuffix(name, "_test.go") && !strings.HasSuffix(name, ".md")
}

// Guard answers what refuses the checkout at dir: where the tag release.toml
// names exists, every input of the binary that differs between that tag and
// the working tree, files git does not track yet among them. A tag not cut
// yet refuses nothing: the push to main that carries the new version cuts it
// (kern-release.yml). The answer is empty where the released binary is the
// one the checkout builds.
func Guard(r Release, dir string) (released bool, changed []string, err error) {
	if _, err := git(dir, "rev-parse", "-q", "--verify", "refs/tags/"+r.Tag+"^{commit}"); err != nil {
		return false, nil, nil
	}
	folders, files, err := Inputs(r, dir)
	if err != nil {
		return true, nil, err
	}
	out, err := git(dir, "diff", "--name-only", "--no-renames", r.Tag, "--")
	if err != nil {
		return true, nil, err
	}
	// Files not added yet count too, so a run before the commit sees them.
	untracked, err := git(dir, "ls-files", "--others", "--exclude-standard", "--full-name")
	if err != nil {
		return true, nil, err
	}
	for _, name := range strings.Split(strings.TrimSpace(out+"\n"+untracked), "\n") {
		if name != "" && Input(folders, files, name) {
			changed = append(changed, name)
		}
	}
	return true, changed, nil
}

// KindsVariable names the release kind a work branch states for each binary,
// `<binary>=<kind>` joined by commas, as SE's work_tickets.py suite and CI
// set it from the field report's **Component kinds:**. Unset, as on a
// landing and on main, the guard refuses as it always did.
const KindsVariable = "SE_COMPONENT_KINDS"

// Kinds reads KindsVariable's value: each binary and its kind, patch, minor
// or major; an entry it cannot read is an error naming it.
func Kinds(value string) (map[string]string, error) {
	kinds := map[string]string{}
	for _, entry := range strings.Split(value, ",") {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		name, kind, ok := strings.Cut(entry, "=")
		if !ok || !binary.MatchString(name) || (kind != "patch" && kind != "minor" && kind != "major") {
			return nil, fmt.Errorf("%s: %q is no <binary>=patch|minor|major", KindsVariable, entry)
		}
		kinds[name] = kind
	}
	return kinds, nil
}

// listed is the part of go list's JSON the guard reads.
type listed struct {
	Dir        string
	Standard   bool
	GoFiles    []string
	EmbedFiles []string
	Module     *struct{ Dir string }
}

func goList(dir string, args ...string) ([]listed, error) {
	cmd := exec.Command("go", append([]string{"list", "-json"}, args...)...)
	cmd.Dir = dir
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("go list %s in %s: %v: %s", strings.Join(args, " "), dir, err, strings.TrimSpace(stderr.String()))
	}
	var all []listed
	for d := json.NewDecoder(bytes.NewReader(out)); d.More(); {
		var p listed
		if err := d.Decode(&p); err != nil {
			return nil, fmt.Errorf("go list %s in %s: %w", strings.Join(args, " "), dir, err)
		}
		all = append(all, p)
	}
	return all, nil
}

// git runs git in dir through kern's git door.
func git(dir string, args ...string) (string, error) {
	return gitdoor.Run(context.Background(), dir, args...)
}

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

const usage = "usage: release plan [--dir DIR] [--repository OWNER/NAME] | release build [--dir DIR] --out DIR | release guard [--dir DIR]..."

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 || (args[0] != "plan" && args[0] != "build" && args[0] != "guard") {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	if args[0] == "guard" {
		return guard(args[1:], stdout, stderr)
	}
	fs := flag.NewFlagSet("release "+args[0], flag.ContinueOnError)
	fs.SetOutput(stderr)
	repository := fs.String("repository", "", "the repository the release is published into (plan)")
	out := fs.String("out", "", "the folder the archives and SHA256SUMS go into (build)")
	dir := fs.String("dir", ".", "the folder holding release.toml and the binary's package; kern/ by default, an application's own folder for its binary")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	data, err := os.ReadFile(filepath.Join(*dir, Settings))
	if err != nil {
		fmt.Fprintf(stderr, "release: %v (run it from kern/, or name the application's folder with --dir)\n", err)
		return 2
	}
	r, err := Read(data)
	if err != nil {
		fmt.Fprintf(stderr, "release: %v\n", err)
		return 2
	}
	switch args[0] {
	case "plan":
		if *repository != "" && !strings.EqualFold(*repository, r.Repository) {
			fmt.Fprintf(stderr, "release: %s's download names %s, but this is %s: move the release workflow with the URL, or fix the URL\n",
				Settings, r.Repository, *repository)
			return 2
		}
		fmt.Fprintf(stdout, "version=%s\ntag=%s\nrepository=%s\ndownload=%s\nbinary=%s\n",
			r.Version, r.Tag, r.Repository, r.Download, r.Binary)
		return 0
	default:
		if *out == "" {
			fmt.Fprintln(stderr, usage)
			return 2
		}
		names, err := Build(r, *dir, *out, stderr)
		if err != nil {
			fmt.Fprintf(stderr, "release: %v\n", err)
			return 2
		}
		fmt.Fprintf(stdout, "release: %s, %d archives and SHA256SUMS in %s\n", r.Tag, len(names), *out)
		return 0
	}
}

// dirs is a flag given once per folder.
type dirs []string

func (d *dirs) String() string     { return strings.Join(*d, ",") }
func (d *dirs) Set(v string) error { *d = append(*d, v); return nil }

// guard runs Guard for each folder named, kern/ (the working directory) where
// none is: SE's se.toml [tests.beside.release-guard] names kern's and SE's own.
func guard(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("release guard", flag.ContinueOnError)
	fs.SetOutput(stderr)
	var folders dirs
	fs.Var(&folders, "dir", "a folder holding release.toml and the binary's package; once per binary, the working directory by default")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if len(folders) == 0 {
		folders = dirs{"."}
	}
	value, work := os.LookupEnv(KindsVariable)
	kinds, err := Kinds(value)
	if err != nil {
		fmt.Fprintf(stderr, "release guard: %v\n", err)
		return 2
	}
	code := 0
	for _, dir := range folders {
		data, err := os.ReadFile(filepath.Join(dir, Settings))
		if err != nil {
			fmt.Fprintf(stderr, "release guard: %v\n", err)
			return 2
		}
		r, err := Read(data)
		if err != nil {
			fmt.Fprintf(stderr, "release guard: %v\n", err)
			return 2
		}
		released, changed, err := Guard(r, dir)
		switch {
		case err != nil:
			fmt.Fprintf(stderr, "release guard: %v\n", err)
			return 2
		case !released:
			fmt.Fprintf(stdout, "release guard: %s %s is not cut yet; the push to main that carries it cuts %s\n", r.Binary, r.Version, r.Tag)
		case len(changed) == 0:
			fmt.Fprintf(stdout, "release guard: %s %s: the checkout builds the binary %s holds\n", r.Binary, r.Version, r.Tag)
		case work && kinds[r.Binary] != "":
			fmt.Fprintf(stdout, "release guard: %s is cut, and %d of the %s binary's inputs changed since; "+
				"the field report states %s %s, so the landing assigns its next version\n",
				r.Tag, len(changed), r.Binary, r.Binary, kinds[r.Binary])
		default:
			prefix, _ := git(dir, "rev-parse", "--show-prefix")
			fmt.Fprintf(stderr, "release guard: %s is cut, and %d of the %s binary's inputs changed since: %s; "+
				"state its kind in the field report, **Component kinds:** %s patch|minor|major, so the landing "+
				"assigns the next version, or raise version in %s, so the landing cuts a release that holds them\n",
				r.Tag, len(changed), r.Binary, strings.Join(changed, ", "), r.Binary,
				path.Join(strings.TrimSpace(prefix), Settings))
			code = 1
		}
	}
	return code
}
