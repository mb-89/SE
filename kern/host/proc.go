package host

import (
	"fmt"
	"strconv"
	"strings"
)

// A process's start mark is when the platform says it started, in the
// platform's own units: the same at every read for one process, another for
// the next process that gets its pid. The standing file keeps its core's mark
// (Standing.Proc), so a reader tells its core from a process that reuses the
// core's pid, as after a container restored from its snapshot with the boot
// id it had.

// procMark answers the start mark of the process at pid; empty where the
// platform names none or no process runs there.
func procMark(pid int) string {
	if pid <= 0 {
		return ""
	}
	mark, err := platformProc(pid)
	if err != nil {
		return ""
	}
	return mark
}

// markFromStat reads Linux's /proc/<pid>/stat: its 22nd field, starttime,
// counts the clock ticks from the boot to the process's start. The second
// field, the command's name in parentheses, may itself hold spaces and
// parentheses, so the fields are counted from the last ')'.
func markFromStat(data []byte) (string, error) {
	text := string(data)
	end := strings.LastIndexByte(text, ')')
	if end < 0 {
		return "", fmt.Errorf("stat %q names no command", data)
	}
	// After the command: state (field 3) ... starttime (field 22).
	fields := strings.Fields(text[end+1:])
	if len(fields) < 20 {
		return "", fmt.Errorf("stat holds %d fields after its command, and starttime is the 20th", len(fields))
	}
	ticks, err := strconv.ParseUint(fields[19], 10, 64)
	if err != nil {
		return "", fmt.Errorf("stat's starttime %q: %w", fields[19], err)
	}
	return "ticks-" + strconv.FormatUint(ticks, 10), nil
}

// markFromStartTimeval reads macOS's p_starttime of the process's kinfo_proc,
// the time of its start to the microsecond.
func markFromStartTimeval(sec, usec int64) (string, error) {
	if sec <= 0 || usec < 0 || usec >= 1e6 {
		return "", fmt.Errorf("p_starttime %d.%06d names no start", sec, usec)
	}
	return fmt.Sprintf("started-%d.%06d", sec, usec), nil
}

// markFromFiletime reads Windows's creation time of the process
// (GetProcessTimes), in 100 ns steps since 1601.
func markFromFiletime(high, low uint32) (string, error) {
	ft := uint64(high)<<32 | uint64(low)
	if ft == 0 {
		return "", fmt.Errorf("the creation time is zero")
	}
	return "created-" + strconv.FormatUint(ft, 10), nil
}
