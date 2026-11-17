package main

import "golang.org/x/sys/unix"

// ioctlReadTermios is the request that reads a terminal's termios.
const ioctlReadTermios = unix.TCGETS
