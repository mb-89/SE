package host

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// Each platform's source of the boot id reads its own answer: Linux's
// boot_id file, macOS's kern.boottime, Windows's boot counter. The fakes run
// on every platform, so a leg that cannot reach the other sources still
// holds their reading.
func TestEachPlatformsBootSourceReadsItsFake(t *testing.T) {
	t.Parallel()
	if got, err := bootFromProc([]byte("8a1c2f9e-3b4d-4e5f-9a0b-1c2d3e4f5a6b\n")); err != nil || got != "8a1c2f9e-3b4d-4e5f-9a0b-1c2d3e4f5a6b" {
		t.Fatalf("Linux's boot_id reads as %q, %v", got, err)
	}
	if _, err := bootFromProc([]byte("\n")); err == nil {
		t.Fatal("an empty boot_id reads as a boot")
	}
	if got, err := bootFromTimeval(1763078400, 42); err != nil || got != "boottime-1763078400.000042" {
		t.Fatalf("macOS's kern.boottime reads as %q, %v", got, err)
	}
	if _, err := bootFromTimeval(0, 0); err == nil {
		t.Fatal("a zero kern.boottime reads as a boot")
	}
	if got, err := bootFromCounter([]byte{0x2a, 0x01, 0, 0}); err != nil || got != "bootid-298" {
		t.Fatalf("Windows's BootId reads as %q, %v", got, err)
	}
	if _, err := bootFromCounter([]byte{1, 2}); err == nil {
		t.Fatal("a BootId of two bytes reads as a boot")
	}
}

// The running platform names its boot, the same id on every read.
func TestThePlatformNamesItsBoot(t *testing.T) {
	t.Parallel()
	first, err := platformBoot()
	switch runtime.GOOS {
	case "linux", "darwin", "windows":
		if err != nil || first == "" {
			t.Fatalf("%s names no boot: %q, %v", runtime.GOOS, first, err)
		}
	default:
		t.Skipf("%s names no boot", runtime.GOOS)
	}
	if again, _ := platformBoot(); again != first {
		t.Fatalf("the boot reads as %q, then as %q", first, again)
	}
}

// A test's boot id stands in for the platform's.
func TestTheBootEnvStandsInForThePlatform(t *testing.T) {
	t.Setenv(BootEnv, "boot-a")
	if got := Boot(); got != "boot-a" {
		t.Fatalf("Boot reads %q under %s=boot-a", got, BootEnv)
	}
	if earlierBoot("boot-a") || !earlierBoot("boot-b") || earlierBoot("") {
		t.Fatal("earlierBoot tells boots apart wrongly")
	}
}

// The lines of a core's run are those from its own start line on: an
// earlier boot that handed out the same pid wrote lines before it.
func TestARunsLinesStartAtItsStartLine(t *testing.T) {
	t.Parallel()
	at := time.Date(2026, 11, 14, 1, 2, 3, 0, time.UTC)
	log := strings.Join([]string{
		StartLine("kern", at, "boot-a", 255),
		"kern: serving /work, pid 255, bus nats://127.0.0.1:1",
		"kern: the earlier boot's last word",
		StartLine("kern", at.Add(time.Hour), "boot-b", 255),
		"kern: serving /work, pid 255, bus nats://127.0.0.1:2",
	}, "\n") + "\n"
	if got := runLines(log, "boot-b", 255); len(got) != 2 || !strings.Contains(got[1], "127.0.0.1:2") {
		t.Fatalf("boot-b's run reads %q", got)
	}
	if got := runLines(log, "boot-a", 255); len(got) != 5 || got[0] != "kern: start 2026-11-14T01:02:03Z, boot boot-a, pid 255" {
		t.Fatalf("boot-a's run reads %q", got)
	}
	if got := runLines(log, "boot-c", 255); got != nil {
		t.Fatalf("a run with no start line reads %q", got)
	}
	if got := StartLine("kern", at, "", 7); got != "kern: start 2026-11-14T01:02:03Z, boot unknown, pid 7" {
		t.Fatalf("a start line of no boot reads %q", got)
	}
}

func writeStandingOf(t *testing.T, root, boot string, pid int) {
	t.Helper()
	data, _ := json.Marshal(Standing{Contract: Contract, Pid: pid, Boot: boot, Root: root, Bus: "nats://127.0.0.1:1", Port: 1})
	if err := os.MkdirAll(filepath.Join(root, Runtime), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(StandingPath(root), data, 0o600); err != nil {
		t.Fatal(err)
	}
}

// After a restored boot the standing file of the earlier boot's core reads
// as ErrEarlierBoot, not as a core that ended without its end, and goes
// without a report; a core of this boot that vanished is reported with the
// lines of its own run alone.
func TestARestoredBootReportsNoEarlierBootsCore(t *testing.T) {
	root := t.TempDir()
	at := time.Date(2026, 11, 14, 1, 2, 3, 0, time.UTC)
	if err := os.MkdirAll(filepath.Join(root, Runtime), 0o700); err != nil {
		t.Fatal(err)
	}
	log := StartLine("kern", at, "boot-a", 4242) + "\nkern: serving, of boot-a\n"
	if err := os.WriteFile(LogPath(root), []byte(log), 0o600); err != nil {
		t.Fatal(err)
	}
	writeStandingOf(t, root, "boot-a", 4242)

	t.Setenv(BootEnv, "boot-b")
	_, err := ReadStanding(root)
	if !errors.Is(err, ErrEarlierBoot) || !errors.Is(err, ErrNotRunning) || errors.Is(err, ErrVanished) {
		t.Fatalf("the earlier boot's standing file reads as %v, and wants ErrEarlierBoot, not vanished", err)
	}
	if said, ok := TakeVanished(root); ok {
		t.Fatalf("the earlier boot's core is reported: %q", said)
	}
	if _, err := os.Stat(StandingPath(root)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("the earlier boot's standing file stays: %v", err)
	}

	// This boot's core, of a pid that runs nowhere, is reported with its own lines.
	log += StartLine("kern", at.Add(time.Hour), "boot-b", 4242) + "\nkern: serving, of boot-b\n"
	if err := os.WriteFile(LogPath(root), []byte(log), 0o600); err != nil {
		t.Fatal(err)
	}
	writeStandingOf(t, root, "boot-b", 4242)
	said, ok := TakeVanished(root)
	if !ok || strings.Contains(said, "boot-a") || !strings.Contains(said, "of boot-b") {
		t.Fatalf("this boot's vanished core is reported as %q, %v, and wants its own lines alone", said, ok)
	}
}

// The cause a core that ended at its start left is told in its boot alone.
func TestACauseOfAnEarlierBootIsNotTold(t *testing.T) {
	root := t.TempDir()
	t.Setenv(BootEnv, "boot-a")
	if err := RecordDied(root, "kern serve: the cause"); err != nil {
		t.Fatal(err)
	}
	if got := ReadDied(root); got != "kern serve: the cause" {
		t.Fatalf("this boot's cause reads %q", got)
	}
	t.Setenv(BootEnv, "boot-b")
	if got := TakeDied(root); got != "" {
		t.Fatalf("the earlier boot's cause is told: %q", got)
	}
	if _, err := os.Stat(DiedPath(root)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("the earlier boot's cause stays: %v", err)
	}
}
