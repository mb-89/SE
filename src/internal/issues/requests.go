package issues

import (
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/modules/io/disk"
	"github.com/mb-89/SE/src/modules/io/github"
)

// RequestsFile is where each se command run in a workspace records the
// GitHub requests it made, one line each: when, the command, how many. The
// fleet shares the owner's one token, so the requests are counted where they
// are made, and land adds up its checkout's into the landing facts.
const RequestsFile = ".se/.runtime/requests.log"

// RecordRequests appends that command made n requests at at to the ledger of
// the workspace dir. A run that made none records nothing.
func RecordRequests(d disk.Disk, dir, command string, n int, at time.Time) error {
	if n <= 0 {
		return nil
	}
	path := filepath.Join(dir, RequestsFile)
	if err := d.MkdirAll(filepath.Dir(path)); err != nil {
		return err
	}
	f, err := d.Append(path)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(f, "%s\t%s\t%d\n", at.UTC().Format(time.RFC3339), command, n)
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	return err
}

// Requests adds up the requests the ledger of the workspace dir records;
// none where it records nothing. A line it cannot read counts nothing.
func Requests(d disk.Disk, dir string) (int, error) {
	data, err := d.ReadFile(filepath.Join(dir, RequestsFile))
	if errors.Is(err, fs.ErrNotExist) {
		return 0, nil
	}
	if err != nil {
		return 0, err
	}
	total := 0
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Split(line, "\t")
		if n, err := strconv.Atoi(f[len(f)-1]); err == nil && len(f) == 3 {
			total += n
		}
	}
	return total, nil
}

// RateLimitsFile is where each se command run in a workspace records each
// request GitHub refused it for a rate limit, one line each: when, the
// command, the HTTP status, the seconds it waited for the reset, and
// "waited", or "gave up" where the reset lay past the ceiling. land adds
// them up into the landing facts, so the retro counts the waits.
const RateLimitsFile = ".se/.runtime/ratelimits.log"

// RecordRefusals appends the rate-limit refusals that command met to the
// ledger of the workspace dir. A run that met none records nothing.
func RecordRefusals(d disk.Disk, dir, command string, refused []github.Refusal) error {
	if len(refused) == 0 {
		return nil
	}
	path := filepath.Join(dir, RateLimitsFile)
	if err := d.MkdirAll(filepath.Dir(path)); err != nil {
		return err
	}
	f, err := d.Append(path)
	if err != nil {
		return err
	}
	for _, r := range refused {
		how := "waited"
		if r.GaveUp {
			how = "gave up"
		}
		if _, err = fmt.Fprintf(f, "%s\t%s\t%d\t%d\t%s\n", r.At.UTC().Format(time.RFC3339), command, r.Status, int(r.Wait.Round(time.Second)/time.Second), how); err != nil {
			break
		}
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	return err
}

// Waits are the rate-limit refusals a workspace met: how many, and how long
// se waited for the resets all told.
type Waits struct {
	Refusals int
	Wait     time.Duration
}

// add counts refused in.
func (w Waits) add(refused []github.Refusal) Waits {
	for _, r := range refused {
		w.Refusals++
		w.Wait += r.Wait
	}
	return w
}

// RateLimitWaits adds up the rate-limit refusals the ledger of the workspace
// dir records; none where it records nothing. A line it cannot read counts
// nothing.
func RateLimitWaits(d disk.Disk, dir string) (Waits, error) {
	data, err := d.ReadFile(filepath.Join(dir, RateLimitsFile))
	if errors.Is(err, fs.ErrNotExist) {
		return Waits{}, nil
	}
	if err != nil {
		return Waits{}, err
	}
	var w Waits
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Split(line, "\t")
		if len(f) != 5 {
			continue
		}
		if s, err := strconv.Atoi(f[3]); err == nil && s >= 0 {
			w.Refusals++
			w.Wait += time.Duration(s) * time.Second
		}
	}
	return w, nil
}
