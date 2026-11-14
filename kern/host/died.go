package host

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// diedFile, under Runtime, holds what a core that ended at its start said: the
// cause its serve wrote to the core's log, until a hook reports it in the
// session (TakeDied) or a core of the checkout stands (Serve removes it).
const diedFile = "core.died"

// DiedLines is how many of the cause's first lines a report carries; the core's
// log holds all of it.
const DiedLines = 8

// DiedPath is the file of a core that ended at its start, in a checkout.
func DiedPath(root string) string { return filepath.Join(root, Runtime, diedFile) }

// diedBoot heads the file of a core that ended at its start with its boot.
const diedBoot = "boot: "

// RecordDied writes what a core that ends at its start said, headed by its
// boot, so a status and the next hook of that boot name the cause where
// nothing else would: the core's log is read by nobody, and a hook fails open
// without a word.
func RecordDied(root, said string) error {
	if err := os.MkdirAll(filepath.Join(root, Runtime), 0o700); err != nil {
		return err
	}
	head := ""
	if boot := Boot(); boot != "" {
		head = diedBoot + boot + "\n"
	}
	return os.WriteFile(DiedPath(root), []byte(head+strings.TrimRight(said, "\n")+"\n"), 0o600)
}

// ReadDied answers what the last core of the checkout said as it ended at its
// start, its first DiedLines lines; empty where none did since a core stood,
// or where that core ended in an earlier boot.
func ReadDied(root string) string {
	data, err := os.ReadFile(DiedPath(root))
	if err != nil {
		return ""
	}
	text := string(data)
	if rest, ok := strings.CutPrefix(text, diedBoot); ok {
		boot, said, _ := strings.Cut(rest, "\n")
		if earlierBoot(boot) {
			return ""
		}
		text = said
	}
	lines := strings.Split(strings.TrimRight(text, "\n"), "\n")
	if len(lines) > DiedLines {
		lines = append(lines[:DiedLines], "…")
	}
	return strings.Join(lines, "\n")
}

// TakeDied answers ReadDied and removes the file, so one report names it once.
func TakeDied(root string) string {
	said := ReadDied(root)
	if err := os.Remove(DiedPath(root)); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return ""
	}
	return said
}

// TakeVanished answers the last DiedLines lines of the core's run in its log
// (runLines) where the standing file names a core of this boot whose process
// runs nowhere, or that another process holds now, or whose bus is gone
// (ErrReused), and removes that file, so
// one report names it once; false where it names none. The file of a core of
// an earlier boot (ErrEarlierBoot) is removed without a report: that core
// ended with its boot.
func TakeVanished(root string) (string, bool) {
	var s Standing
	data, err := os.ReadFile(StandingPath(root))
	if err != nil || json.Unmarshal(data, &s) != nil || s.Pid == 0 {
		return "", false
	}
	if earlierBoot(s.Boot) {
		dropStanding(root, s.Pid)
		return "", false
	}
	if judge(s) == nil {
		return "", false
	}
	dropStanding(root, s.Pid)
	log, _ := os.ReadFile(LogPath(root))
	lines := runLines(string(log), s.Boot, s.Pid)
	if lines == nil {
		return fmt.Sprintf("(none: no start line of pid %d in boot %s)", s.Pid, s.Boot), true
	}
	if len(lines) > DiedLines {
		lines = lines[len(lines)-DiedLines:]
	}
	return strings.Join(lines, "\n"), true
}
