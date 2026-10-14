package disk

import "github.com/mb-89/SE/src/index"

// Module is the disk on the index: an I/O module.
var Module = index.Declare("io/disk", "The files and folders SE reads, writes, lists, locks and replaces.", index.IO())

func init() { index.Register(Module) }
