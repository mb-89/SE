package issues

import (
	"bytes"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

// gh is GitHub's own I/O module (#63), so it is run here and not through proc.

// GH runs gh with these arguments and answers what it printed.
type GH func(args ...string) ([]byte, error)

// Gh is the gh CLI on this machine; it owns the authentication.
func Gh(args ...string) ([]byte, error) {
	cmd := exec.Command("gh", args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if errors.Is(err, exec.ErrNotFound) {
		return nil, errors.New("gh is missing; RUNME.sh names how to install it")
	}
	if err != nil {
		return nil, fmt.Errorf("gh %s: %v: %s", strings.Join(args, " "), err, strings.TrimSpace(stderr.String()))
	}
	return out, nil
}
