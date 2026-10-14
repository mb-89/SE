package battery_test

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/mb-89/SE/src/internal/battery"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// inBox runs every program in the box's environment: its PATH, HOME and SE_HOME.
type inBox struct {
	proc.Procs
	b box
}

func (p inBox) Run(c proc.Cmd) error {
	c.Env = p.b.env()
	return p.Procs.Run(c)
}

func TestFmtRunsEveryFormatterTheBatteryChecksWhereItChecksIt(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "deadcode", "claude")
	// The linters log the folder they run in, as well as their call.
	write(t, filepath.Join(b.bin, "golangci-lint"), `#!/bin/sh
[ "$1" = --version ] && { echo "golangci-lint has version `+pin(t, "GOLANGCI_LINT")+` built with go"; exit 0; }
echo "golangci-lint $* in ${PWD#`+b.dir+`/}" >>`+b.log+"\n", 0o755)
	write(t, filepath.Join(b.bin, "biome"), `#!/bin/sh
[ "$1" = --version ] && { echo "Version: `+pin(t, "BIOME")+`"; exit 0; }
echo "biome $* in ${PWD#`+b.dir+`/}" >>`+b.log+"\n", 0o755)
	if _, err := battery.Format(inBox{proc.Real(), b}, b.dir); err != nil {
		t.Fatal(err)
	}
	if got, want := b.calls(t), "golangci-lint fmt ./... in src\nbiome check --write in src/plugin\n"; got != want {
		t.Errorf("calls = %q, want %q", got, want)
	}
}

func TestFmtInstallsAMissingFormatterFirst(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "deadcode", "claude")
	if _, err := battery.Format(inBox{proc.Real(), b}, b.dir); err != nil {
		t.Fatal(err)
	}
	got := strings.Split(strings.TrimSpace(b.calls(t)), "\n")
	want := []string{
		"curl https://github.com/golangci/golangci-lint/releases/download/v" + pin(t, "GOLANGCI_LINT") + "/" + asset(t, "golangci-lint"),
		"curl https://github.com/golangci/golangci-lint/releases/download/v" + pin(t, "GOLANGCI_LINT") + "/golangci-lint-" + pin(t, "GOLANGCI_LINT") + "-checksums.txt",
		"curl https://github.com/biomejs/biome/releases/download/%40biomejs%2Fbiome%40" + pin(t, "BIOME") + "/" + asset(t, "biome"),
		"golangci-lint fmt ./...",
		"biome check --write",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("calls =\n%s\nwant\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}

func TestAFailedFormatterFailsFmt(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "deadcode", "claude", "golangci-lint")
	write(t, filepath.Join(b.bin, "biome"), `#!/bin/sh
[ "$1" = --version ] && { echo "Version: `+pin(t, "BIOME")+`"; exit 0; }
echo "biome: 1 error left"; exit 1
`, 0o755)
	if _, err := battery.Format(inBox{proc.Real(), b}, b.dir); err == nil || !strings.Contains(err.Error(), "1 error left") {
		t.Errorf("err = %v, want biome's finding", err)
	}
}

func TestFmtNeedsTheToolsScript(t *testing.T) {
	t.Parallel()
	if _, err := battery.Format(proc.Real(), t.TempDir()); err == nil {
		t.Error("formatted a checkout without the tools script")
	}
}
