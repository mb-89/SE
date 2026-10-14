package battery_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// linters puts stubs of the pinned linters on bin, at the versions tools.sh
// pins, which log each call but their version's.
func linters(t *testing.T, bin, log string) {
	t.Helper()
	stub(t, bin, "golangci-lint", `[ "$1" = --version ] && { echo "golangci-lint has version `+pin(t, "GOLANGCI_LINT")+` built with go"; exit 0; }
echo "golangci-lint $*" >>`+log)
	stub(t, bin, "biome", `[ "$1" = --version ] && { echo "Version: `+pin(t, "BIOME")+`"; exit 0; }
echo "biome $*" >>`+log)
}

// onPath runs every program on a PATH of bin alone, as check does.
type onPath struct {
	proc.Procs
	bin string
}

func (p onPath) Run(c proc.Cmd) error {
	c.Env = []string{"PATH=" + p.bin}
	for _, v := range os.Environ() {
		if !strings.HasPrefix(v, "PATH=") {
			c.Env = append(c.Env, v)
		}
	}
	return p.Procs.Run(c)
}

func TestFmtRunsEveryFormatterTheBatteryChecks(t *testing.T) {
	t.Parallel()
	dir, bin, log := freshBox(t)
	linters(t, bin, log)
	if _, err := battery.Format(onPath{proc.Real(), bin}, dir); err != nil {
		t.Fatal(err)
	}
	if got, want := calls(t, log), "golangci-lint fmt ./...\nbiome check --write\n"; got != want {
		t.Errorf("calls = %q, want %q", got, want)
	}
}

func TestFmtInstallsAMissingFormatterFirst(t *testing.T) {
	t.Parallel()
	ln, err := exec.LookPath("ln")
	if err != nil {
		t.Skipf("ln is missing: %v", err)
	}
	dir, bin, log := freshBox(t)
	stand := t.TempDir()
	linters(t, stand, log)
	// The installs log their call and put the linter on the PATH.
	stub(t, bin, "go", `[ "$1 $2" = "env GOPATH" ] && { echo `+filepath.Join(bin, "gopath")+`; exit 0; }
echo "go $*" >>`+log+`; `+ln+` -s `+filepath.Join(stand, "golangci-lint")+` `+filepath.Join(bin, "golangci-lint"))
	stub(t, bin, "npm", `echo "npm $*" >>`+log+`; `+ln+` -s `+filepath.Join(stand, "biome")+` `+filepath.Join(bin, "biome"))
	if _, err := battery.Format(onPath{proc.Real(), bin}, dir); err != nil {
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
	t.Parallel()
	dir, bin, log := freshBox(t)
	linters(t, bin, log)
	stub(t, bin, "biome", `[ "$1" = --version ] && { echo "Version: `+pin(t, "BIOME")+`"; exit 0; }
echo "biome: 1 error left"; exit 1`)
	if _, err := battery.Format(onPath{proc.Real(), bin}, dir); err == nil || !strings.Contains(err.Error(), "1 error left") {
		t.Errorf("err = %v, want biome's finding", err)
	}
}

func TestFmtNeedsTheToolsScript(t *testing.T) {
	t.Parallel()
	if _, err := battery.Format(proc.Real(), t.TempDir()); err == nil {
		t.Error("formatted a checkout without the tools script")
	}
}
