package battery_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// freshBox is a checkout holding the real check.sh and tools.sh, on a PATH
// with the shell's tools and stubs of go, claude and npm logging each call,
// but no linters. The go and npm stubs install a stub linter at its pin.
func freshBox(t *testing.T) (dir, bin, log string) {
	t.Helper()
	dir, bin = t.TempDir(), t.TempDir()
	log = filepath.Join(bin, "calls")
	for _, sub := range []string{"tests", "src/plugin"} {
		if err := os.MkdirAll(filepath.Join(dir, sub), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"check.sh", "tools.sh"} {
		script, err := os.ReadFile("../../../tests/" + name)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "tests", name), script, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	for _, tool := range []string{"sh", "grep", "cut", "date", "dirname", "mkdir", "rm", "chmod"} {
		path, err := exec.LookPath(tool)
		if err != nil {
			t.Skipf("%s is missing: %v", tool, err)
		}
		if err := os.Symlink(path, filepath.Join(bin, tool)); err != nil {
			t.Fatal(err)
		}
	}
	golangci := `#!/bin/sh\necho "golangci-lint has version ` + pin(t, "GOLANGCI_LINT") + ` built with go"\n`
	biome := `#!/bin/sh\necho "Version: ` + pin(t, "BIOME") + `"\n`
	stub(t, bin, "go", `[ "$1 $2" = "env GOPATH" ] && { echo `+filepath.Join(bin, "gopath")+`; exit 0; }
echo "go $*" >>`+log+`
[ "$1" = install ] && { printf '`+golangci+`' >`+filepath.Join(bin, "golangci-lint")+`; chmod +x `+filepath.Join(bin, "golangci-lint")+`; }
exit 0`)
	stub(t, bin, "npm", `echo "npm $*" >>`+log+`
printf '`+biome+`' >`+filepath.Join(bin, "biome")+`; chmod +x `+filepath.Join(bin, "biome"))
	stub(t, bin, "claude", `echo "claude $*" >>`+log)
	t.Setenv("PATH", bin)
	return dir, bin, log
}

// pin is the version tools.sh pins for name.
func pin(t *testing.T, name string) string {
	t.Helper()
	script, err := os.ReadFile("../../../tests/tools.sh")
	if err != nil {
		t.Fatal(err)
	}
	_, v, _ := strings.Cut(string(script), "\n"+name+"=")
	v, _, _ = strings.Cut(v, "\n")
	return v
}

func stub(t *testing.T, bin, name, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(bin, name), []byte("#!/bin/sh\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
}

func check(t *testing.T, dir string) (string, error) {
	t.Helper()
	cmd := exec.Command("sh", "tests/check.sh")
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	return string(out), err
}

func calls(t *testing.T, log string) string {
	t.Helper()
	data, err := os.ReadFile(log)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	return string(data)
}

func TestTheBatteryInstallsThePinnedLintersABoxLacks(t *testing.T) {
	dir, _, log := freshBox(t)
	if out, err := check(t, dir); err != nil {
		t.Fatalf("check.sh failed: %v\n%s", err, out)
	}
	got := calls(t, log)
	for _, want := range []string{
		"go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v" + pin(t, "GOLANGCI_LINT"),
		"npm install -g @biomejs/biome@" + pin(t, "BIOME"),
		"go -C src run ./cmd/battery gotest " + dir + " ./...",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("no %q among the calls:\n%s", want, got)
		}
	}
}

func TestTheBatteryInstallsNothingWhereTheLintersStand(t *testing.T) {
	dir, bin, log := freshBox(t)
	stub(t, bin, "golangci-lint", `echo "golangci-lint has version `+pin(t, "GOLANGCI_LINT")+` built with go"`)
	stub(t, bin, "biome", `echo "Version: `+pin(t, "BIOME")+`"`)
	if out, err := check(t, dir); err != nil {
		t.Fatalf("check.sh failed: %v\n%s", err, out)
	}
	if got := calls(t, log); strings.Contains(got, "install") {
		t.Errorf("installed what stands:\n%s", got)
	}
}

func TestAFailedInstallStopsTheBattery(t *testing.T) {
	dir, bin, log := freshBox(t)
	stub(t, bin, "npm", "exit 1")
	out, err := check(t, dir)
	if err == nil {
		t.Fatalf("check.sh passed without biome:\n%s", out)
	}
	if strings.Contains(calls(t, log), "gotest") {
		t.Errorf("the battery ran without its linters:\n%s", out)
	}
}
