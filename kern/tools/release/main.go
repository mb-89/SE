// Command release builds kern's release from release.toml: the bare binary
// for linux, darwin and windows on amd64 and arm64, each archived, and a
// SHA256SUMS file over the archives (kern/README.md "Release").
//
//	go run ./tools/release plan  [--repository OWNER/NAME]   print version=, tag=, repository= and download=
//	go run ./tools/release build --out DIR                   build the six archives and SHA256SUMS into DIR
//
// plan refuses when --repository is given and the download URL names another
// repository, so a moved URL never publishes into the old one. Run from kern/.
// Exit codes: 0 done, 2 a usage, settings or build error.
package main

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/pelletier/go-toml/v2"
)

// Settings is the file that owns kern's version and its release URL.
const Settings = "release.toml"

// Binary is the bare core's name, and its package.
const (
	Binary  = "kern"
	Package = "./cmd/kern"
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
}

var (
	semver   = regexp.MustCompile(`^\d+\.\d+\.\d+$`)
	download = regexp.MustCompile(`^https://github\.com/([\w.-]+/[\w.-]+)/releases/download/([\w.-]*\{version\}[\w.-]*)$`)
)

// Read reads release.toml's text.
func Read(data []byte) (Release, error) {
	var doc struct {
		Version  string `toml:"version"`
		Download string `toml:"download"`
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
	return Release{
		Version:    doc.Version,
		Download:   strings.ReplaceAll(doc.Download, "{version}", doc.Version),
		Repository: m[1],
		Tag:        strings.ReplaceAll(m[2], "{version}", doc.Version),
	}, nil
}

// Archive names a target's archive: kern-<version>-<os>-<arch>.tar.gz, .zip on Windows.
func Archive(version string, t Target) string {
	ext := ".tar.gz"
	if t.OS == "windows" {
		ext = ".zip"
	}
	return fmt.Sprintf("%s-%s-%s-%s%s", Binary, version, t.OS, t.Arch, ext)
}

// Executable names the binary inside a target's archive.
func Executable(t Target) string {
	if t.OS == "windows" {
		return Binary + ".exe"
	}
	return Binary
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

// Build cross-compiles the bare core for every target into out, archives each
// and writes SHA256SUMS; it answers the archives' names.
func Build(r Release, out string, log io.Writer) ([]string, error) {
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
		bin := filepath.Join(scratch, t.OS+"-"+t.Arch, Executable(t))
		start := time.Now()
		build := exec.Command("go", "build", "-trimpath", "-ldflags=-s -w", "-o", bin, Package)
		build.Env = append(os.Environ(), "GOOS="+t.OS, "GOARCH="+t.Arch, "CGO_ENABLED=0")
		build.Stdout, build.Stderr = log, log
		if err := build.Run(); err != nil {
			return nil, fmt.Errorf("go build for %s/%s: %w", t.OS, t.Arch, err)
		}
		data, err := os.ReadFile(bin)
		if err != nil {
			return nil, err
		}
		name := Archive(r.Version, t)
		if err := Pack(filepath.Join(out, name), Executable(t), data); err != nil {
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

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

const usage = "usage: release plan [--repository OWNER/NAME] | release build --out DIR"

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 || (args[0] != "plan" && args[0] != "build") {
		fmt.Fprintln(stderr, usage)
		return 2
	}
	fs := flag.NewFlagSet("release "+args[0], flag.ContinueOnError)
	fs.SetOutput(stderr)
	repository := fs.String("repository", "", "the repository the release is published into (plan)")
	out := fs.String("out", "", "the folder the archives and SHA256SUMS go into (build)")
	if err := fs.Parse(args[1:]); err != nil {
		return 2
	}
	data, err := os.ReadFile(Settings)
	if err != nil {
		fmt.Fprintf(stderr, "release: %v (run it from kern/)\n", err)
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
		fmt.Fprintf(stdout, "version=%s\ntag=%s\nrepository=%s\ndownload=%s\n", r.Version, r.Tag, r.Repository, r.Download)
		return 0
	default:
		if *out == "" {
			fmt.Fprintln(stderr, usage)
			return 2
		}
		names, err := Build(r, *out, stderr)
		if err != nil {
			fmt.Fprintf(stderr, "release: %v\n", err)
			return 2
		}
		fmt.Fprintf(stdout, "release: %s, %d archives and SHA256SUMS in %s\n", r.Tag, len(names), *out)
		return 0
	}
}
