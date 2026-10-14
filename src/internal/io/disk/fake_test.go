package disk_test

import (
	"path/filepath"
	"testing"

	"github.com/mb-89/SE/src/internal/io/disk"
)

func TestTheFakeDiskKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) (disk.Disk, string) {
		d := disk.NewFake()
		dir, err := d.MkdirTemp("", "contract-*")
		must(t, err)
		return d, dir
	})
}

func TestTheFakeDiskHoldsEachInstanceApart(t *testing.T) {
	t.Parallel()
	a, b := disk.NewFake(), disk.NewFake()
	p := filepath.Join(string(filepath.Separator), "ws", "f")
	must(t, a.MkdirAll(filepath.Dir(p)))
	must(t, a.WriteFile(p, []byte("a")))
	if ok, _ := b.Exists(p); ok {
		t.Fatal("one fake sees another's file")
	}
}

func TestTheFakeDiskReadsARelativePathUnderTheRoot(t *testing.T) {
	t.Parallel()
	d := disk.NewFake()
	must(t, d.WriteFile("f", []byte("x")))
	if got := read(t, d, filepath.Join(string(filepath.Separator), "f")); got != "x" {
		t.Fatalf("read %q", got)
	}
}
