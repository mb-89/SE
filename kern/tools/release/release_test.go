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
)

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
	moved, err := Read([]byte("version = \"1.2.3\"\ndownload = \"https://github.com/mb-89/kern/releases/download/v{version}\"\n"))
	if err != nil || moved.Tag != "v1.2.3" || moved.Repository != "mb-89/kern" {
		t.Fatalf("the move is the URL alone: got %+v, %v", moved, err)
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
	if want := "version=0.1.0\ntag=v0.1.0\nrepository=mb-89/kern\ndownload=https://github.com/mb-89/kern/releases/download/v0.1.0\n"; out.String() != want {
		t.Fatalf("plan printed %q", out.String())
	}
}

func TestTheSixTargetsAndTheirArchiveNames(t *testing.T) {
	var got []string
	for _, target := range Targets {
		got = append(got, Archive("0.1.0", target)+":"+Executable(target))
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
