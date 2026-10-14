package battery

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/mb-89/SE/src/internal/io/disk"
	"github.com/mb-89/SE/src/internal/io/proc"
)

// Stamp is the built-in path, in the checkout, of the stamp: the file the
// battery writes once it passed, committed with the work, holding the hash
// of the tree it passed with the stamp itself left out (Hash). CI computes
// the same hash of the tree it checked out and skips the battery where the
// two match (se fleet trust). The issues instance's config/stamp names the
// path; .gitattributes merges it as a union, so two branches that both
// changed it merge without a conflict, into a stamp that names no hash.
const Stamp = "tests/battery.stamp"

// hashed is what Hash answers: a SHA-256, in hex.
var hashed = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Hash answers the hash of commit rev's tree in the checkout at top, with
// the file at stamp left out: SHA-256 over every entry git ls-tree lists
// recursively (mode, type, object and path) but the stamp's. Committing a
// new stamp leaves the hash as it was.
func Hash(procs proc.Procs, top, rev, stamp string) (string, error) {
	out, err := proc.Output(procs, proc.Cmd{Name: "git", Args: []string{"ls-tree", "-r", "-z", "--full-tree", rev}, Dir: top})
	if err != nil {
		return "", err
	}
	h := sha256.New()
	for _, entry := range strings.Split(out, "\x00") {
		if _, path, _ := strings.Cut(entry, "\t"); entry == "" || path == stamp {
			continue
		}
		h.Write([]byte(entry + "\x00"))
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// Tree answers Hash of HEAD in the worktree at top, or "" where it has
// changes not committed but for the stamp: a dirty worktree is not the tree
// its HEAD names, and a stamp the battery wrote before is no change.
func Tree(procs proc.Procs, top, stamp string) (string, error) {
	dirty, err := proc.Output(procs, proc.Cmd{Name: "git", Args: []string{"status", "--porcelain", "--", ".", ":(exclude)" + stamp}, Dir: top})
	if err != nil || dirty != "" {
		return "", err
	}
	return Hash(procs, top, "HEAD", stamp)
}

// Pass writes started into the stamp at top as the tree the battery passed,
// where the worktree still holds it, clean: a commit made or a file changed
// while the battery ran is not what it checked. It writes nothing where
// started is "" (the battery started on a dirty worktree), and says so.
func Pass(d disk.Disk, procs proc.Procs, top, stamp, started string) (string, error) {
	if started == "" {
		return "the worktree had changes not committed when the battery started, so it writes no stamp", nil
	}
	now, err := Tree(procs, top, stamp)
	if err != nil {
		return "", err
	}
	if now != started {
		return fmt.Sprintf("the worktree moved from tree %s while the battery ran, so it writes no stamp", started), nil
	}
	path := filepath.Join(top, stamp)
	if err := d.MkdirAll(filepath.Dir(path)); err != nil {
		return "", err
	}
	if err := d.WriteFile(path, []byte(started+"\n")); err != nil {
		return "", err
	}
	return fmt.Sprintf("the battery passed tree %s, written to %s", started, stamp), nil
}

// Stamped answers what the stamp says as commit rev holds it, in the
// checkout at top: "" where rev holds none; ok is false where it names no
// hash.
func Stamped(procs proc.Procs, top, rev, stamp string) (said string, ok bool, err error) {
	held, err := proc.Output(procs, proc.Cmd{Name: "git", Args: []string{"ls-tree", "--name-only", "--full-tree", rev, "--", stamp}, Dir: top})
	if err != nil || held == "" {
		return "", false, err
	}
	said, err = proc.Output(procs, proc.Cmd{Name: "git", Args: []string{"show", rev + ":" + stamp}, Dir: top})
	if err != nil {
		return "", false, err
	}
	return said, hashed.MatchString(said), nil
}

// Trusted says why the battery need not run on commit rev in the checkout at
// top: the stamp rev holds names Hash of rev's tree. Where it does not (main
// moved since, the stamp is missing or stale), the error says why, and CI
// runs the battery. It is trust in one's own boxes, not a proof.
func Trusted(procs proc.Procs, top, rev, stamp string) (string, error) {
	hash, err := Hash(procs, top, rev, stamp)
	if err != nil {
		return "", err
	}
	said, ok, err := Stamped(procs, top, rev, stamp)
	switch {
	case err != nil:
		return "", err
	case said == "":
		return "", fmt.Errorf("%s holds no stamp at %s: no battery passed it", rev, stamp)
	case !ok:
		return "", fmt.Errorf("the stamp %s in %s names no hash: %q", stamp, rev, said)
	case said != hash:
		return "", fmt.Errorf("the stamp %s names tree %s, and %s holds tree %s: it changed since the battery passed (main moved, say)", stamp, said, rev, hash)
	}
	return fmt.Sprintf("the battery passed tree %s, as %s in %s says", hash, stamp, rev), nil
}
