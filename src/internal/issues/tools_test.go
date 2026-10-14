package issues_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/issues"
)

// fakeBox is a checkout holding the real tools script, on a PATH that has the
// shell's tools and stubs of go and npm logging each call, but no linters.
func fakeBox(t *testing.T) (dir, bin, log string) {
	t.Helper()
	dir, bin = t.TempDir(), t.TempDir()
	log = filepath.Join(bin, "calls")
	script, err := os.ReadFile("../../../" + issues.ToolsScript)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "tests"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, issues.ToolsScript), script, 0o644); err != nil {
		t.Fatal(err)
	}
	for _, tool := range []string{"sh", "grep", "cut"} {
		path, err := exec.LookPath(tool)
		if err != nil {
			t.Skipf("%s is missing: %v", tool, err)
		}
		if err := os.Symlink(path, filepath.Join(bin, tool)); err != nil {
			t.Fatal(err)
		}
	}
	stub(t, bin, "go", `[ "$1 $2" = "env GOPATH" ] && { echo `+filepath.Join(bin, "gopath")+`; exit 0; }
echo "go $*" >>`+log)
	stub(t, bin, "npm", `echo "npm $*" >>`+log)
	t.Setenv("PATH", bin)
	return dir, bin, log
}

func stub(t *testing.T, bin, name, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(bin, name), []byte("#!/bin/sh\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
}

func calls(t *testing.T, log string) string {
	t.Helper()
	data, err := os.ReadFile(log)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	return string(data)
}

func TestAClaimInstallsThePinnedLintersABoxLacks(t *testing.T) {
	dir, _, log := fakeBox(t)
	if err := issues.ReadyTools(dir); err != nil {
		t.Fatal(err)
	}
	got := calls(t, log)
	for _, want := range []string{"go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v", "npm install -g @biomejs/biome@"} {
		if !strings.Contains(got, want) {
			t.Errorf("no %q among the calls:\n%s", want, got)
		}
	}
}

func TestAClaimInstallsNothingWhereTheLintersStand(t *testing.T) {
	dir, bin, log := fakeBox(t)
	script, err := os.ReadFile(filepath.Join(dir, issues.ToolsScript))
	if err != nil {
		t.Fatal(err)
	}
	pin := func(name string) string {
		_, v, _ := strings.Cut(string(script), "\n"+name+"=")
		v, _, _ = strings.Cut(v, "\n")
		return v
	}
	stub(t, bin, "golangci-lint", `echo "golangci-lint has version `+pin("GOLANGCI_LINT")+` built with go"`)
	stub(t, bin, "biome", `echo "Version: `+pin("BIOME")+`"`)
	if err := issues.ReadyTools(dir); err != nil {
		t.Fatal(err)
	}
	if got := calls(t, log); got != "" {
		t.Errorf("installed what stands:\n%s", got)
	}
}

func TestAFailedInstallNamesTheFix(t *testing.T) {
	dir, bin, _ := fakeBox(t)
	stub(t, bin, "go", `[ "$1 $2" = "env GOPATH" ] && { echo `+filepath.Join(bin, "gopath")+`; exit 0; }
exit 1`)
	err := issues.ReadyTools(dir)
	if err == nil || !strings.Contains(err.Error(), "sh "+issues.ToolsScript+" install") {
		t.Errorf("err = %v, want it to name sh %s install", err, issues.ToolsScript)
	}
}

func TestACheckoutWithoutToolsNeedsNone(t *testing.T) {
	if err := issues.ReadyTools(t.TempDir()); err != nil {
		t.Error(err)
	}
}

// pinned is the version the tools script in dir pins for name.
func pinned(t *testing.T, dir, name string) string {
	t.Helper()
	script, err := os.ReadFile(filepath.Join(dir, issues.ToolsScript))
	if err != nil {
		t.Fatal(err)
	}
	_, v, _ := strings.Cut(string(script), "\n"+name+"=")
	v, _, _ = strings.Cut(v, "\n")
	return v
}

// linters puts stubs of the pinned linters on bin, at the versions the script
// pins, which log each call but their version's.
func linters(t *testing.T, dir, bin, log string) {
	t.Helper()
	stub(t, bin, "golangci-lint", `[ "$1" = --version ] && { echo "golangci-lint has version `+pinned(t, dir, "GOLANGCI_LINT")+` built with go"; exit 0; }
echo "golangci-lint $*" >>`+log)
	stub(t, bin, "biome", `[ "$1" = --version ] && { echo "Version: `+pinned(t, dir, "BIOME")+`"; exit 0; }
echo "biome $*" >>`+log)
}

func TestFmtRunsEveryFormatterTheBatteryChecks(t *testing.T) {
	dir, bin, log := fakeBox(t)
	linters(t, dir, bin, log)
	if _, err := issues.Format(dir); err != nil {
		t.Fatal(err)
	}
	if got, want := calls(t, log), "golangci-lint fmt ./...\nbiome check --write\n"; got != want {
		t.Errorf("calls = %q, want %q", got, want)
	}
}

func TestFmtInstallsAMissingFormatterFirst(t *testing.T) {
	ln, err := exec.LookPath("ln")
	if err != nil {
		t.Skipf("ln is missing: %v", err)
	}
	dir, bin, log := fakeBox(t)
	stand := t.TempDir()
	linters(t, dir, stand, log)
	// The installs log their call and put the linter on the PATH.
	stub(t, bin, "go", `[ "$1 $2" = "env GOPATH" ] && { echo `+filepath.Join(bin, "gopath")+`; exit 0; }
echo "go $*" >>`+log+`; `+ln+` -s `+filepath.Join(stand, "golangci-lint")+` `+filepath.Join(bin, "golangci-lint"))
	stub(t, bin, "npm", `echo "npm $*" >>`+log+`; `+ln+` -s `+filepath.Join(stand, "biome")+` `+filepath.Join(bin, "biome"))
	if _, err := issues.Format(dir); err != nil {
		t.Fatal(err)
	}
	got := strings.Split(strings.TrimSpace(calls(t, log)), "\n")
	want := []string{"go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v", "npm install -g @biomejs/biome@", "golangci-lint fmt ./...", "biome check --write"}
	if len(got) != len(want) {
		t.Fatalf("calls = %q, want %q in turn", got, want)
	}
	for i := range want {
		if !strings.HasPrefix(got[i], want[i]) {
			t.Errorf("call %d = %q, want %q", i, got[i], want[i])
		}
	}
}

func TestAFailedFormatterFailsFmt(t *testing.T) {
	dir, bin, log := fakeBox(t)
	linters(t, dir, bin, log)
	stub(t, bin, "biome", `[ "$1" = --version ] && { echo "Version: `+pinned(t, dir, "BIOME")+`"; exit 0; }
echo "biome: 1 error left"; exit 1`)
	if _, err := issues.Format(dir); err == nil || !strings.Contains(err.Error(), "1 error left") {
		t.Errorf("err = %v, want biome's finding", err)
	}
}

func TestFmtNeedsTheToolsScript(t *testing.T) {
	if _, err := issues.Format(t.TempDir()); err == nil {
		t.Error("formatted a checkout without the tools script")
	}
}
