package host

import (
	"encoding/binary"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// BootEnv names the boot id kern reads instead of the platform's: a test
// restores a boot by giving the core one id and the next hook another.
const BootEnv = "KERN_BOOT_ID"

// Boot answers the machine's boot id: the same for every process of one boot,
// another after a restart. A cloud environment restored from its snapshot
// keeps the checkout's files and hands out the last boot's pids, so the boot
// id, not the pid, tells a core of this boot from one of an earlier boot.
// Empty where the platform names none; then a standing file is judged by its
// pid and bus alone (ReadStanding).
func Boot() string {
	if id := os.Getenv(BootEnv); id != "" {
		return id
	}
	id, err := platformBoot()
	if err != nil {
		return ""
	}
	return id
}

// earlierBoot says whether boot is known and another than this boot's.
func earlierBoot(boot string) bool {
	now := Boot()
	return boot != "" && now != "" && boot != now
}

// bootFromProc reads Linux's /proc/sys/kernel/random/boot_id: a UUID the
// kernel draws at each boot.
func bootFromProc(data []byte) (string, error) {
	id := strings.TrimSpace(string(data))
	if id == "" || strings.ContainsAny(id, " \t\n") {
		return "", fmt.Errorf("boot_id %q names no boot", data)
	}
	return id, nil
}

// bootFromTimeval reads macOS's kern.boottime, the time of the boot to the
// microsecond, which no later boot repeats.
func bootFromTimeval(sec, usec int64) (string, error) {
	if sec <= 0 || usec < 0 || usec >= 1e6 {
		return "", fmt.Errorf("kern.boottime %d.%06d names no boot", sec, usec)
	}
	return fmt.Sprintf("boottime-%d.%06d", sec, usec), nil
}

// bootFromCounter reads Windows's boot counter, the REG_DWORD BootId under
// HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory
// Management\PrefetchParameters, which each boot raises by one.
func bootFromCounter(data []byte) (string, error) {
	if len(data) != 4 {
		return "", fmt.Errorf("BootId holds %d bytes, and a REG_DWORD holds 4", len(data))
	}
	return "bootid-" + strconv.FormatUint(uint64(binary.LittleEndian.Uint32(data)), 10), nil
}

// noBoot is how a start line names a boot the platform names no id for.
const noBoot = "unknown"

// StartLine is the line a serve writes to the core's log first, on every
// run, so the log tells one core's run, and one boot's, from the next.
func StartLine(name string, at time.Time, boot string, pid int) string {
	if boot == "" {
		boot = noBoot
	}
	return fmt.Sprintf("%s: start %s, boot %s, pid %d", name, at.UTC().Format(time.RFC3339), boot, pid)
}

var startLine = regexp.MustCompile(`^\S+: start \S+, boot (\S+), pid (\d+)$`)

// runLines answers the lines of the core's log the run of pid in boot wrote:
// those from its start line on; none where no start line names that run.
func runLines(log string, boot string, pid int) []string {
	if boot == "" {
		boot = noBoot
	}
	lines := strings.Split(strings.TrimRight(log, "\n"), "\n")
	for i := len(lines) - 1; i >= 0; i-- {
		m := startLine.FindStringSubmatch(lines[i])
		if m != nil && m[1] == boot && m[2] == strconv.Itoa(pid) {
			return lines[i:]
		}
	}
	return nil
}
