package host

import (
	"os"
	"os/exec"
	"runtime"
	"testing"
)

// Each platform's start mark is read from its source's fake, on every
// platform, so a parser no CI leg runs natively is still held.
func TestEachPlatformsProcSourceReadsItsFake(t *testing.T) {
	stat := "4242 (se (a) b) S 1 4242 4242 0 -1 4194560 100 0 0 0 1 2 0 0 20 0 9 0 987654 1000 100 18446744073709551615\n"
	if got, err := markFromStat([]byte(stat)); err != nil || got != "ticks-987654" {
		t.Fatalf("linux stat reads %q, %v, and wants ticks-987654", got, err)
	}
	for _, bad := range []string{"", "4242 no command", "4242 (se) S 1 2 3"} {
		if got, err := markFromStat([]byte(bad)); err == nil {
			t.Fatalf("linux stat %q reads %q, and wants a refusal", bad, got)
		}
	}
	if got, err := markFromStartTimeval(1763000000, 42); err != nil || got != "started-1763000000.000042" {
		t.Fatalf("darwin p_starttime reads %q, %v", got, err)
	}
	if _, err := markFromStartTimeval(0, 0); err == nil {
		t.Fatal("darwin's zero p_starttime names a start")
	}
	if got, err := markFromFiletime(1, 2); err != nil || got != "created-4294967298" {
		t.Fatalf("windows creation time reads %q, %v", got, err)
	}
	if _, err := markFromFiletime(0, 0); err == nil {
		t.Fatal("windows's zero creation time names a start")
	}
}

// The platform names this process's start mark, the same at every read, and
// another for its parent, which started before it; none for a pid that runs
// nowhere. Linux counts in clock ticks, so two processes forked within one
// tick share a mark: a reused pid is told by the mark together with the bus
// (judge).
func TestThePlatformNamesAProcesssStart(t *testing.T) {
	switch runtime.GOOS {
	case "linux", "darwin", "windows":
	default:
		t.Skipf("%s names no start of a process", runtime.GOOS)
	}
	me := procMark(os.Getpid())
	if me == "" || procMark(os.Getpid()) != me {
		t.Fatalf("this process's start mark reads %q, and wants one, the same at each read", me)
	}
	if parent := procMark(os.Getppid()); parent == "" || parent == me {
		t.Fatalf("the parent's start mark reads %q, and this process's %q: want another", parent, me)
	}
	child := exec.Command(os.Args[0], "-test.run=^$")
	if err := child.Run(); err != nil {
		t.Fatal(err)
	}
	if got := procMark(child.Process.Pid); got != "" {
		t.Fatalf("the ended child's pid still names a start: %q", got)
	}
}
