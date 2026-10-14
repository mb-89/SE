package proc

import "github.com/mb-89/SE/src/index"

// Module is the machine's programs on the index: an I/O module.
var Module = index.Declare("io/proc", "The programs SE starts: git, go, the linters, check.sh and se itself.", index.IO())

func init() { index.Register(Module) }
