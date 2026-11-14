package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	gitdoor "github.com/mb-89/kern/git"
	"github.com/mb-89/kern/git/gitfake"
)

// Every test reaches git through kern's git door, on its fake.
func TestMain(m *testing.M) {
	gitdoor.Use(gitfake.New())
	os.Unsetenv(KindsVariable) // a work branch's kinds are each test's own
	os.Exit(m.Run())
}

func TestReleaseTomlResolvesTheTagAndTheRepositoryFromTheOneURL(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", Settings))
	if err != nil {
		t.Fatal(err)
	}
	r, err := Read(data)
	if err != nil {
		t.Fatal(err)
	}
	if r.Tag != "kern-v"+r.Version || r.Repository != "mb-89/SE" {
		t.Fatalf("while incubated, kern releases as SE's kern-v<version>: got %+v", r)
	}
	if r.Download != "https://github.com/mb-89/SE/releases/download/kern-v"+r.Version {
		t.Fatalf("download base: %s", r.Download)
	}
	if r.Binary != DefaultBinary || r.Package != DefaultPackage {
		t.Fatalf("kern's release.toml names no binary, so it is the bare core's: got %q %q", r.Binary, r.Package)
	}
	moved, err := Read([]byte("version = \"1.2.3\"\ndownload = \"https://github.com/mb-89/kern/releases/download/v{version}\"\n"))
	if err != nil || moved.Tag != "v1.2.3" || moved.Repository != "mb-89/kern" {
		t.Fatalf("the move is the URL alone: got %+v, %v", moved, err)
	}
}

func TestAnApplicationReleaseTomlNamesItsOwnBinaryAndPackage(t *testing.T) {
	// SE's own binary, core plus its Go components, releases as se-v<version>;
	// the tag and repository are the one URL's, as kern's are.
	app, err := Read([]byte("version = \"0.1.0\"\n" +
		"download = \"https://github.com/mb-89/SE/releases/download/se-v{version}\"\n" +
		"binary = \"se\"\npackage = \"./cmd/se\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	if app.Binary != "se" || app.Package != "./cmd/se" || app.Tag != "se-v0.1.0" || app.Repository != "mb-89/SE" {
		t.Fatalf("an application names its own binary: got %+v", app)
	}
	if got := Archive(app, Target{"linux", "amd64"}); got != "se-0.1.0-linux-amd64.tar.gz" {
		t.Fatalf("the archive carries the binary's name: %s", got)
	}
	if _, err := Read([]byte("version = \"0.1.0\"\ndownload = \"https://github.com/o/n/releases/download/v{version}\"\nbinary = \"Se Core\"\n")); err == nil {
		t.Fatal("accepted a binary name that is no lower-case name")
	}
}

func TestReadRefusesAVersionOrURLItCannotPublish(t *testing.T) {
	for _, text := range []string{
		"version = \"0.1\"\ndownload = \"https://github.com/o/n/releases/download/v{version}\"\n",
		"version = \"0.1.0\"\ndownload = \"https://github.com/o/n/releases/download/v0.1.0\"\n",
		"version = \"0.1.0\"\ndownload = \"https://example.com/o/n/releases/download/v{version}\"\n",
	} {
		if _, err := Read([]byte(text)); err == nil {
			t.Errorf("accepted %q", text)
		}
	}
}

func TestPlanRefusesToPublishIntoARepositoryTheURLDoesNotName(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, Settings), []byte("version = \"0.1.0\"\ndownload = \"https://github.com/mb-89/kern/releases/download/v{version}\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	t.Chdir(dir)
	var out, errs bytes.Buffer
	if code := run([]string{"plan", "--repository", "mb-89/SE"}, &out, &errs); code != 2 || !strings.Contains(errs.String(), "names mb-89/kern, but this is mb-89/SE") {
		t.Fatalf("code %d, %s", code, errs.String())
	}
	out.Reset()
	if code := run([]string{"plan", "--repository", "MB-89/kern"}, &out, &errs); code != 0 {
		t.Fatalf("code %d, %s", code, errs.String())
	}
	if want := "version=0.1.0\ntag=v0.1.0\nrepository=mb-89/kern\ndownload=https://github.com/mb-89/kern/releases/download/v0.1.0\nbinary=kern\n"; out.String() != want {
		t.Fatalf("plan printed %q", out.String())
	}
}

func TestTheSixTargetsAndTheirArchiveNames(t *testing.T) {
	r := Release{Version: "0.1.0", Binary: DefaultBinary}
	var got []string
	for _, target := range Targets {
		got = append(got, Archive(r, target)+":"+Executable(r, target))
	}
	want := []string{
		"kern-0.1.0-darwin-amd64.tar.gz:kern", "kern-0.1.0-darwin-arm64.tar.gz:kern",
		"kern-0.1.0-linux-amd64.tar.gz:kern", "kern-0.1.0-linux-arm64.tar.gz:kern",
		"kern-0.1.0-windows-amd64.zip:kern.exe", "kern-0.1.0-windows-arm64.zip:kern.exe",
	}
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("got %v", got)
	}
}

func TestPackWritesOneExecutableEntryAndTheSameBytesEveryTime(t *testing.T) {
	dir := t.TempDir()
	binary := []byte("\x7fELF a binary")
	for _, name := range []string{"a.tar.gz", "a.zip"} {
		path := filepath.Join(dir, name)
		if err := Pack(path, "kern", binary); err != nil {
			t.Fatal(err)
		}
		first, _ := os.ReadFile(path)
		if err := Pack(path, "kern", binary); err != nil {
			t.Fatal(err)
		}
		again, _ := os.ReadFile(path)
		if !bytes.Equal(first, again) {
			t.Errorf("%s: two packs of one binary differ", name)
		}
		entry, mode, data := unpack(t, path)
		if entry != "kern" || mode != 0o755 || !bytes.Equal(data, binary) {
			t.Errorf("%s: entry %q mode %o data %q", name, entry, mode, data)
		}
	}
}

func unpack(t *testing.T, path string) (string, os.FileMode, []byte) {
	t.Helper()
	if strings.HasSuffix(path, ".zip") {
		z, err := zip.OpenReader(path)
		if err != nil {
			t.Fatal(err)
		}
		defer z.Close()
		if len(z.File) != 1 {
			t.Fatalf("%d entries", len(z.File))
		}
		r, err := z.File[0].Open()
		if err != nil {
			t.Fatal(err)
		}
		data, _ := io.ReadAll(r)
		return z.File[0].Name, z.File[0].Mode().Perm(), data
	}
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	g, err := gzip.NewReader(f)
	if err != nil {
		t.Fatal(err)
	}
	r := tar.NewReader(g)
	h, err := r.Next()
	if err != nil {
		t.Fatal(err)
	}
	data, _ := io.ReadAll(r)
	if _, err := r.Next(); err != io.EOF {
		t.Fatalf("a second entry: %v", err)
	}
	return h.Name, os.FileMode(h.Mode).Perm(), data
}

func TestSumsListsEveryArchiveSortedAsSha256sumReadsIt(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"b.zip", "a.tar.gz"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(name), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := Sums(dir, []string{"b.zip", "a.tar.gz"}); err != nil {
		t.Fatal(err)
	}
	got, _ := os.ReadFile(filepath.Join(dir, "SHA256SUMS"))
	line := func(name string) string {
		sum := sha256.Sum256([]byte(name))
		return hex.EncodeToString(sum[:]) + "  " + name + "\n"
	}
	if string(got) != line("a.tar.gz")+line("b.zip") {
		t.Fatalf("SHA256SUMS:\n%s", got)
	}
}

// A repository with one application binary: cmd/app imports lib, which
// embeds a file; tagged as released at 0.1.0.
func releasedRepository(t *testing.T) string {
	t.Helper()
	repo := t.TempDir()
	app := filepath.Join(repo, "app")
	files := map[string]string{
		filepath.Join("app", Settings):                   "version = \"0.1.0\"\ndownload = \"https://github.com/example/app/releases/download/app-v{version}\"\nbinary = \"app\"\npackage = \"./cmd/app\"\n",
		filepath.Join("app", "go.mod"):                   "module example.com/app\n\ngo 1.24\n",
		filepath.Join("app", "cmd", "app", "main.go"):    "package main\n\nimport \"example.com/app/lib\"\n\nfunc main() { println(lib.Name()) }\n",
		filepath.Join("app", "lib", "lib.go"):            "package lib\n\nimport _ \"embed\"\n\n//go:embed name.txt\nvar name string\n\nfunc Name() string { return name }\n",
		filepath.Join("app", "lib", "name.txt"):          "app\n",
		filepath.Join("app", "lib", "lib_test.go"):       "package lib\n",
		filepath.Join("app", "lib", "README.md"):         "# lib\n",
		filepath.Join("app", "tools", "other", "x.go"):   "package other\n",
		filepath.Join("app", "lib", "testdata", "a.txt"): "a\n",
	}
	for name, text := range files {
		write(t, filepath.Join(repo, name), text)
	}
	run := func(args ...string) {
		t.Helper()
		if _, err := git(repo, append([]string{"-c", "user.name=alice", "-c", "user.email=alice@example.com", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"}, args...)...); err != nil {
			t.Fatal(err)
		}
	}
	run("init", "-q")
	run("add", "-A")
	run("commit", "-q", "-m", "released")
	run("tag", "app-v0.1.0")
	return app
}

func write(t *testing.T, name, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(name), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(name, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

// The guard SE's suite runs (se.toml [tests.beside.release-guard]): a change
// to a file the binary is built from, once its version is released, refuses
// the checkout until the version is raised; tests, prose, test data and
// packages the binary does not import refuse nothing.
func TestGuardRefusesABinaryInputChangedSinceItsReleasedTag(t *testing.T) {
	app := releasedRepository(t)
	guard := func() (int, string) {
		var out, errs bytes.Buffer
		code := run([]string{"guard", "--dir", app}, &out, &errs)
		return code, out.String() + errs.String()
	}
	if code, said := guard(); code != 0 || !strings.Contains(said, "the checkout builds the binary app-v0.1.0 holds") {
		t.Fatalf("at the tag: code %d, %s", code, said)
	}
	for _, name := range []string{
		filepath.Join("lib", "lib_test.go"), filepath.Join("lib", "README.md"),
		filepath.Join("lib", "testdata", "a.txt"), filepath.Join("tools", "other", "x.go"),
	} {
		write(t, filepath.Join(app, name), "package lib\n// changed\n")
	}
	if code, said := guard(); code != 0 {
		t.Fatalf("no input changed: code %d, %s", code, said)
	}
	for _, input := range []string{filepath.Join("lib", "name.txt"), "go.mod", filepath.Join("lib", "lib.go")} {
		original, err := os.ReadFile(filepath.Join(app, input))
		if err != nil {
			t.Fatal(err)
		}
		write(t, filepath.Join(app, input), string(original)+"\n")
		code, said := guard()
		want := "app/" + filepath.ToSlash(input)
		if code != 1 || !strings.Contains(said, "app-v0.1.0 is cut, and 1 of the app binary's inputs changed since: "+want+";") ||
			!strings.Contains(said, "raise version in app/release.toml") {
			t.Fatalf("%s changed: code %d, %s", want, code, said)
		}
		write(t, filepath.Join(app, input), string(original))
	}
	write(t, filepath.Join(app, "lib", "new.go"), "package lib\n")
	if code, said := guard(); code != 1 || !strings.Contains(said, "app/lib/new.go") {
		t.Fatalf("a file added to an imported package: code %d, %s", code, said)
	}
	settings, err := os.ReadFile(filepath.Join(app, Settings))
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(app, Settings), strings.Replace(string(settings), "0.1.0", "0.2.0", 1))
	if code, said := guard(); code != 0 || !strings.Contains(said, "app 0.2.0 is not cut yet; the push to main that carries it cuts app-v0.2.0") {
		t.Fatalf("the version raised: code %d, %s", code, said)
	}
}

// On a work branch (KindsVariable set from its field report) a changed input
// passes where the binary's kind is stated, as the landing assigns the
// version; one not stated refuses, naming the field report's line. Unset, as
// on a landing and on main, it refuses as before.
func TestOnAWorkBranchTheGuardPassesAChangedInputWhoseKindIsStated(t *testing.T) {
	app := releasedRepository(t)
	guard := func() (int, string) {
		var out, errs bytes.Buffer
		code := run([]string{"guard", "--dir", app}, &out, &errs)
		return code, out.String() + errs.String()
	}
	write(t, filepath.Join(app, "lib", "lib.go"), "package lib\n\nfunc Name() string { return \"changed\" }\n")
	t.Setenv(KindsVariable, "other=minor, app=patch")
	if code, said := guard(); code != 0 || !strings.Contains(said, "the field report states app patch, so the landing assigns its next version") {
		t.Fatalf("kind stated: code %d, %s", code, said)
	}
	t.Setenv(KindsVariable, "other=minor")
	if code, said := guard(); code != 1 || !strings.Contains(said, "**Component kinds:** app patch|minor|major") {
		t.Fatalf("kind not stated: code %d, %s", code, said)
	}
	t.Setenv(KindsVariable, "app=huge")
	if code, said := guard(); code != 2 || !strings.Contains(said, `"app=huge" is no <binary>=patch|minor|major`) {
		t.Fatalf("kind unreadable: code %d, %s", code, said)
	}
}
