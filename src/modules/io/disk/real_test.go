package disk_test

import (
	"testing"

	"github.com/mb-89/SE/src/modules/io/disk"
)

func TestTheRealDiskKeepsTheContract(t *testing.T) {
	t.Parallel()
	contract(t, func(t *testing.T) (disk.Disk, string) { return disk.Real(), t.TempDir() })
}
