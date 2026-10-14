package issues

import (
	"errors"
	"fmt"
	"io/fs"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/mb-89/SE/src/internal/io/disk"
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
