package battery_test

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// box is a checkout holding the real check.sh and tools.sh, with a HOME of its
// own, on a PATH with the shell's tools and stubs of the tools it has, and a
// curl that serves every release file from a fake download source. Every stub
// logs its calls; the fake go installs a stub of the program it is asked for.
type box struct {
	dir, bin, home, src, log string
}

// the shell's tools tools.sh, check.sh and the fake curl call.
var shellTools = []string{
	"sh", "bash", "grep", "cut", "date", "dirname", "mkdir", "rm", "chmod", "cp",
	"find", "head", "mktemp", "tar", "gzip", "sha256sum", "uname", "cat", "basename",
}

func newBox(t *testing.T, has ...string) box {
	t.Helper()
	if runtime.GOOS != "linux" {
		t.Skip("the fake download source serves Linux's release files")
	}
	b := box{dir: t.TempDir(), bin: t.TempDir(), home: t.TempDir(), src: t.TempDir()}
	b.log = filepath.Join(b.bin, "calls")
	for _, sub := range []string{"tests", "src/plugin"} {
		if err := os.MkdirAll(filepath.Join(b.dir, sub), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"check.sh", "tools.sh"} {
		script, err := os.ReadFile("../../../tests/" + name)
		if err != nil {
			t.Fatal(err)
		}
		write(t, filepath.Join(b.dir, "tests", name), string(script), 0o644)
	}
	for _, tool := range shellTools {
		path, err := exec.LookPath(tool)
		if err != nil {
			t.Skipf("%s is missing: %v", tool, err)
		}
		if err := os.Symlink(path, filepath.Join(b.bin, tool)); err != nil {
			t.Fatal(err)
		}
	}
	write(t, filepath.Join(b.bin, "curl"), `#!/bin/sh
out=
while [ $# -gt 0 ]; do
  case $1 in
    -o) out=$2; shift ;;
    -*) ;;
    *) url=$1 ;;
  esac
  shift
done
echo "curl $url" >>`+b.log+`
file=`+b.src+`/$(basename "$url")
[ -f "$file" ] || exit 22
if [ -n "$out" ]; then cp "$file" "$out"; else cat "$file"; fi
`, 0o755)
	for _, tool := range has {
		write(t, filepath.Join(b.bin, tool), b.stub(t, tool), 0o755)
	}
	b.release(t)
	return b
}

// stub is the script standing in for tool, logging each call.
func (b box) stub(t *testing.T, tool string) string {
	t.Helper()
	switch tool {
	case "golangci-lint":
		return "#!/bin/sh\n[ \"$1\" = --version ] && { echo \"golangci-lint has version " + pin(t, "GOLANGCI_LINT") + " built with go\"; exit 0; }\necho \"golangci-lint $*\" >>" + b.log + "\n"
	case "biome":
		return "#!/bin/sh\n[ \"$1\" = --version ] && { echo \"Version: " + pin(t, "BIOME") + "\"; exit 0; }\necho \"biome $*\" >>" + b.log + "\n"
	case "go":
		return `#!/bin/sh
[ "$1 $2" = "env GOPATH" ] && { echo ` + filepath.Join(b.home, "gopath") + `; exit 0; }
echo "go $*" >>` + b.log + `
[ "$1" = install ] && [ -n "${GOBIN:-}" ] && { exe=$(basename "${2%@*}"); printf '#!/bin/sh\n' >"$GOBIN/$exe"; chmod +x "$GOBIN/$exe"; }
exit 0
`
	}
	return "#!/bin/sh\necho \"" + tool + " $*\" >>" + b.log + "\n"
}

// release fills the fake download source with this platform's release files,
// laid out as each release lays them out, and their checksums.
func (b box) release(t *testing.T) {
	t.Helper()
	gh, golangci, goArchive, biome := asset(t, "gh"), asset(t, "golangci-lint"), asset(t, "go"), asset(t, "biome")
	files := map[string][]byte{
		gh:        tgz(t, map[string]string{strings.TrimSuffix(gh, ".tar.gz") + "/bin/gh": b.stub(t, "gh")}),
		golangci:  tgz(t, map[string]string{strings.TrimSuffix(golangci, ".tar.gz") + "/golangci-lint": b.stub(t, "golangci-lint")}),
		goArchive: tgz(t, map[string]string{"go/bin/go": b.stub(t, "go")}),
		biome:     []byte(b.stub(t, "biome")),
		"install.sh": []byte(`mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\necho "claude $*" >>` + b.log + `\n' >"$HOME/.local/bin/claude"
chmod +x "$HOME/.local/bin/claude"
`),
	}
	files["gh_"+pin(t, "GH")+"_checksums.txt"] = []byte(sum(files[gh]) + "  " + gh + "\n")
	files["golangci-lint-"+pin(t, "GOLANGCI_LINT")+"-checksums.txt"] = []byte(sum(files[golangci]) + "  " + golangci + "\n")
	files[goArchive+".sha256"] = []byte(sum(files[goArchive]))
	for name, data := range files {
		write(t, filepath.Join(b.src, name), string(data), 0o644)
	}
	// Biome's checksums are pinned in tools.sh, so the box's copy pins the fake's.
	script := filepath.Join(b.dir, "tests", "tools.sh")
	tools, err := os.ReadFile(script)
	if err != nil {
		t.Fatal(err)
	}
	line := "  " + biome + "\n"
	before, after, ok := strings.Cut(string(tools), line)
	if !ok {
		t.Fatalf("tools.sh pins no checksum for %s", biome)
	}
	before = before[:strings.LastIndex(before, "\n")+1]
	write(t, script, before+sum(files[biome])+line+after, 0o644)
}

func (b box) run(t *testing.T, script string, args ...string) (string, error) {
	t.Helper()
	cmd := exec.Command(filepath.Join(b.bin, "sh"), append([]string{script}, args...)...)
	cmd.Dir = b.dir
	cmd.Env = b.env()
	out, err := cmd.CombinedOutput()
	return string(out), err
}

// env is the environment the box's scripts run in.
func (b box) env() []string {
	return env(map[string]string{"PATH": b.bin, "HOME": b.home, "SE_HOME": "", "SHELL": "/bin/bash"})
}

// env is this process's environment with the variables set.
func env(set map[string]string) []string {
	var vars []string
	for _, v := range os.Environ() {
		name, _, _ := strings.Cut(v, "=")
		if _, ok := set[name]; !ok {
			vars = append(vars, v)
		}
	}
	for name, value := range set {
		vars = append(vars, name+"="+value)
	}
	return vars
}

func (b box) calls(t *testing.T) string {
	t.Helper()
	data, err := os.ReadFile(b.log)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	return string(data)
}

// asset is the name tools.sh gives tool's release file on this machine.
func asset(t *testing.T, tool string) string {
	t.Helper()
	out, err := exec.Command("sh", "-c", `. ../../../tests/tools.sh && tools_asset "$0" "$(uname -s)" "$(uname -m)"`, tool).CombinedOutput()
	if err != nil {
		t.Fatalf("tools_asset %s: %v\n%s", tool, err, out)
	}
	return strings.TrimSpace(string(out))
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

func tgz(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for name, body := range files {
		if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(body)), Typeflag: tar.TypeReg}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write([]byte(body)); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func sum(data []byte) string {
	s := sha256.Sum256(data)
	return hex.EncodeToString(s[:])
}

func write(t *testing.T, path, body string, mode os.FileMode) {
	t.Helper()
	if err := os.WriteFile(path, []byte(body), mode); err != nil {
		t.Fatal(err)
	}
}

func TestRUNMEsInstallStepInstallsEveryToolABoxLacks(t *testing.T) {
	t.Parallel()
	b := newBox(t)
	if out, err := b.run(t, "tests/tools.sh", "install"); err != nil {
		t.Fatalf("tools.sh install failed: %v\n%s", err, out)
	}
	seBin := filepath.Join(b.home, ".se", "bin")
	for _, path := range []string{
		filepath.Join(seBin, "gh"),
		filepath.Join(seBin, "golangci-lint"),
		filepath.Join(seBin, "biome"),
		filepath.Join(seBin, "dlv"),
		filepath.Join(seBin, "deadcode"),
		filepath.Join(b.home, ".se", "go", "bin", "go"),
		filepath.Join(b.home, ".local", "bin", "claude"),
	} {
		info, err := os.Stat(path)
		if err != nil || info.Mode()&0o111 == 0 {
			t.Errorf("%s is not an installed program: %v", path, err)
		}
	}
	if got := b.calls(t); !strings.Contains(got, "go install github.com/go-delve/delve/cmd/dlv@v"+pin(t, "DLV")) {
		t.Errorf("dlv was not installed at its pin:\n%s", got)
	}
	if got := b.calls(t); !strings.Contains(got, "go install golang.org/x/tools/cmd/deadcode@v"+pin(t, "DEADCODE")) {
		t.Errorf("deadcode was not installed at its pin:\n%s", got)
	}
	rc, err := os.ReadFile(filepath.Join(b.home, ".bashrc"))
	if err != nil {
		t.Fatal(err)
	}
	want := `export PATH="` + seBin + ":" + filepath.Join(b.home, ".se", "go", "bin") + ":" + filepath.Join(b.home, ".local", "bin") + `:$PATH"`
	if !strings.Contains(string(rc), want) {
		t.Errorf(".bashrc does not put the install on the PATH:\n%s", rc)
	}
	// Run again, it changes nothing that stands.
	if err := os.Remove(b.log); err != nil {
		t.Fatal(err)
	}
	if out, err := b.run(t, "tests/tools.sh", "install"); err != nil {
		t.Fatalf("tools.sh install failed again: %v\n%s", err, out)
	}
	if got := b.calls(t); got != "" {
		t.Errorf("the second install did something:\n%s", got)
	}
	if rc2, _ := os.ReadFile(filepath.Join(b.home, ".bashrc")); string(rc2) != string(rc) {
		t.Errorf(".bashrc changed again:\n%s", rc2)
	}
}

func TestADownloadThatMissesItsChecksumIsNotInstalled(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "dlv", "deadcode", "claude", "golangci-lint", "biome")
	write(t, filepath.Join(b.src, asset(t, "gh")), "tampered", 0o644)
	out, err := b.run(t, "tests/tools.sh", "install")
	if err == nil || !strings.Contains(out, "does not match its checksum") {
		t.Fatalf("installed a tampered gh: %v\n%s", err, out)
	}
	if _, err := os.Stat(filepath.Join(b.home, ".se", "bin", "gh")); err == nil {
		t.Error("the tampered gh is in ~/.se/bin")
	}
}

func TestTheBatteryInstallsThePinnedLintersABoxLacks(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "deadcode", "claude")
	if out, err := b.run(t, "tests/check.sh"); err != nil {
		t.Fatalf("check.sh failed: %v\n%s", err, out)
	}
	got := b.calls(t)
	for _, want := range []string{
		"curl https://github.com/golangci/golangci-lint/releases/download/v" + pin(t, "GOLANGCI_LINT") + "/" + asset(t, "golangci-lint"),
		"curl https://github.com/biomejs/biome/releases/download/%40biomejs%2Fbiome%40" + pin(t, "BIOME") + "/" + asset(t, "biome"),
		"go -C src run ./cmd/battery gotest " + b.dir + " ./...",
		"deadcode -test ./...",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("no %q among the calls:\n%s", want, got)
		}
	}
}

func TestTheBatteryInstallsNothingWhereTheToolsStand(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "deadcode", "claude", "golangci-lint", "biome")
	if out, err := b.run(t, "tests/check.sh"); err != nil {
		t.Fatalf("check.sh failed: %v\n%s", err, out)
	}
	if got := b.calls(t); strings.Contains(got, "curl") || strings.Contains(got, "install") {
		t.Errorf("installed what stands:\n%s", got)
	}
}

func TestAFailedInstallStopsTheBattery(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "deadcode", "claude", "golangci-lint")
	if err := os.Remove(filepath.Join(b.src, asset(t, "biome"))); err != nil {
		t.Fatal(err)
	}
	out, err := b.run(t, "tests/check.sh")
	if err == nil {
		t.Fatalf("check.sh passed without biome:\n%s", out)
	}
	if strings.Contains(b.calls(t), "gotest") {
		t.Errorf("the battery ran without its linters:\n%s", out)
	}
}

// Every platform SE installs on, by what uname says there: the release file
// of each tool, its binary's name, and the PATH line, which Git Bash on
// Windows reads from ~/.bashrc as Linux does.
func TestToolsNamesEachPlatformsReleaseFiles(t *testing.T) {
	t.Parallel()
	if runtime.GOOS == "windows" {
		t.Skip("tools.sh runs under sh")
	}
	gh, golang, golangci := pin(t, "GH"), pin(t, "GO"), pin(t, "GOLANGCI_LINT")
	home := t.TempDir()
	for _, c := range []struct {
		system, machine             string
		gh, golang, golangci, biome string
		exe                         string
	}{
		{"Linux", "x86_64", "gh_" + gh + "_linux_amd64.tar.gz", "go" + golang + ".linux-amd64.tar.gz", "golangci-lint-" + golangci + "-linux-amd64.tar.gz", "biome-linux-x64", "gh"},
		{"Linux", "aarch64", "gh_" + gh + "_linux_arm64.tar.gz", "go" + golang + ".linux-arm64.tar.gz", "golangci-lint-" + golangci + "-linux-arm64.tar.gz", "biome-linux-arm64", "gh"},
		{"Darwin", "arm64", "gh_" + gh + "_macOS_arm64.zip", "go" + golang + ".darwin-arm64.tar.gz", "golangci-lint-" + golangci + "-darwin-arm64.tar.gz", "biome-darwin-arm64", "gh"},
		{"Darwin", "x86_64", "gh_" + gh + "_macOS_amd64.zip", "go" + golang + ".darwin-amd64.tar.gz", "golangci-lint-" + golangci + "-darwin-amd64.tar.gz", "biome-darwin-x64", "gh"},
		{"MINGW64_NT-10.0-19045", "x86_64", "gh_" + gh + "_windows_amd64.zip", "go" + golang + ".windows-amd64.zip", "golangci-lint-" + golangci + "-windows-amd64.zip", "biome-win32-x64.exe", "gh.exe"},
		{"MSYS_NT-10.0-22631", "aarch64", "gh_" + gh + "_windows_arm64.zip", "go" + golang + ".windows-arm64.zip", "golangci-lint-" + golangci + "-windows-arm64.zip", "biome-win32-arm64.exe", "gh.exe"},
	} {
		cmd := exec.Command("sh", "-c", `. ../../../tests/tools.sh
for tool in gh go golangci-lint biome; do tools_asset $tool "$0" "$1"; done
tools_exe gh "$0"
tools_path`, c.system, c.machine)
		cmd.Env = env(map[string]string{"HOME": home, "SE_HOME": ""})
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("%s %s: %v\n%s", c.system, c.machine, err, out)
		}
		want := strings.Join([]string{
			c.gh, c.golang, c.golangci, c.biome, c.exe,
			home + "/.se/bin:" + home + "/.se/go/bin:" + home + "/.local/bin",
		}, "\n") + "\n"
		if string(out) != want {
			t.Errorf("%s %s:\n%s\nwant\n%s", c.system, c.machine, out, want)
		}
	}
	out, err := exec.Command("sh", "-c", `. ../../../tests/tools.sh; tools_platform SunOS x86_64`).CombinedOutput()
	if err == nil || !strings.Contains(string(out), "no release for the system SunOS") {
		t.Errorf("SunOS: %v\n%s", err, out)
	}
}

func TestCodeNothingReachesFailsTheBattery(t *testing.T) {
	t.Parallel()
	b := newBox(t, "go", "gh", "dlv", "claude", "golangci-lint", "biome")
	write(t, filepath.Join(b.bin, "deadcode"), "#!/bin/sh\necho 'internal/x/x.go:3:6: unreachable func: Unused'\n", 0o755)
	out, err := b.run(t, "tests/check.sh")
	if err == nil || !strings.Contains(out, "unreachable func: Unused") || !strings.Contains(out, "delete them") {
		t.Fatalf("check.sh passed with dead code: %v\n%s", err, out)
	}
	if strings.Contains(b.calls(t), "gotest") {
		t.Errorf("the battery went on past dead code:\n%s", out)
	}
}
