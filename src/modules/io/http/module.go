package http

import "github.com/mb-89/SE/src/index"

// Module is the network on the index: an I/O module.
var Module = index.Declare("io/http", "The network SE serves the daemon protocol on and fires the routine over.", index.IO())

func init() { index.Register(Module) }
