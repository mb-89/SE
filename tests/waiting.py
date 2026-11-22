"""How a test waits without the wall clock (tst-002): on an event the awaited process gives, with one
deadline that fires only where the event never comes.

- `Bell`: a socket on this machine that a test's child processes ring as they reach a point, each
  ring a connection carrying one line; the test blocks in `accept` until the rings it awaits came.
- `exclusive`: an operating-system lock on a file, which wakes the next holder as the last one lets
  go, and lets go by itself where its holder dies.
- `settled_run`: `subprocess.run` that returns only once the command and every process it started
  have exited, off Windows: each inherits the write end of a pipe, so its end of file means all
  are gone.
"""
from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

#: The deadline of every wait here: a failure bound, past any run that passes.
DEADLINE_SECONDS = 60.0

#: A child's ring: `python -c RING <port> <line>` connects to the bell and says the line.
RING = ("import socket, sys; s = socket.create_connection(('127.0.0.1', int(sys.argv[1]))); "
        "s.sendall(sys.argv[2].encode()); s.close()")


class Bell:
    """A listening socket on 127.0.0.1; each connection to it is one ring, its bytes its line."""

    def __init__(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(64)
        self.port: int = self.server.getsockname()[1]
        self.heard: list[str] = []

    def shell(self, python: str, line: str) -> str:
        """The shell command that rings this bell with `line` (shell text, quoted by the caller's
        script as it needs), run by `python`, the interpreter's path as the shell names it."""
        return f"\"{python}\" -c \"{RING}\" {self.port} {line}"

    def answer(self, seconds: float = DEADLINE_SECONDS) -> socket.socket:
        """The next connection, as it comes; fails past `seconds`."""
        self.server.settimeout(seconds)
        try:
            connection, _ = self.server.accept()
        except TimeoutError:
            raise AssertionError(f"no ring within {seconds} s; heard {self.heard}") from None
        connection.settimeout(seconds)
        return connection

    def wait(self, enough: Callable[[list[str]], bool],
             seconds: float = DEADLINE_SECONDS) -> list[str]:
        """Every line heard, once `enough` holds of them; fails past `seconds`, naming them."""
        deadline = time.monotonic() + seconds
        while not enough(self.heard):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"the awaited rings did not come within {seconds} s; "
                                     f"heard {self.heard}")
            with self.answer(remaining) as connection:
                chunks = []
                while chunk := connection.recv(4096):
                    chunks.append(chunk)
            self.heard.append(b"".join(chunks).decode("utf-8", errors="replace"))
        return list(self.heard)

    def close(self) -> None:
        self.server.close()


def _kernel32():
    """kernel32 and an OVERLAPPED for its file locks, on the file's first byte."""
    import ctypes
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    return ctypes.WinDLL("kernel32", use_last_error=True), Overlapped()


def _windows_lock(handle, flags: int) -> bool:
    """LockFileEx on the file's first byte: blocks until it is free, or fails at once where
    `flags` holds LOCKFILE_FAIL_IMMEDIATELY."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32, overlapped = _kernel32()
    return bool(kernel32.LockFileEx(wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno())),
                                    wintypes.DWORD(flags), wintypes.DWORD(0), wintypes.DWORD(1),
                                    wintypes.DWORD(0), ctypes.byref(overlapped)))


def _windows_unlock(handle) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32, overlapped = _kernel32()
    kernel32.UnlockFileEx(wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno())), wintypes.DWORD(0),
                          wintypes.DWORD(1), wintypes.DWORD(0), ctypes.byref(overlapped))


EXCLUSIVE, AT_ONCE = 0x2, 0x1  # LOCKFILE_EXCLUSIVE_LOCK, LOCKFILE_FAIL_IMMEDIATELY


def _lock(handle) -> None:
    if os.name == "nt":
        _windows_lock(handle, EXCLUSIVE)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _try_lock(handle) -> bool:
    if os.name == "nt":
        return _windows_lock(handle, EXCLUSIVE | AT_ONCE)
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle) -> None:
    if os.name == "nt":
        _windows_unlock(handle)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def exclusive(path: Path, seconds: float = DEADLINE_SECONDS) -> Iterator[None]:
    """Hold the lock of the file `path` (created where missing) for the body, across processes;
    a holder that dies lets go. Fails past `seconds` of waiting, naming the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    try:
        if not _try_lock(handle):
            taken = threading.Event()
            waiter = threading.Thread(target=lambda: (_lock(handle), taken.set()), daemon=True)
            waiter.start()
            if not taken.wait(seconds):
                raise TimeoutError(f"{path} is still locked after {seconds} s")
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


def settled_run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run(command, **kwargs)`, returned once every process it started has exited
    too (each holds the write end of one pipe until it does). Off Windows only: Windows passes
    no such descriptor, and the run returns as the command exits."""
    if os.name == "nt":
        return subprocess.run(command, **kwargs)
    read, write = os.pipe()
    with os.fdopen(read, "rb") as settled:
        try:
            result = subprocess.run(command, pass_fds=(write,), **kwargs)
        finally:
            os.close(write)
        done = threading.Event()
        threading.Thread(target=lambda: (settled.read(), done.set()), daemon=True).start()
        if not done.wait(DEADLINE_SECONDS):
            raise AssertionError(f"a process {command} started still runs after {DEADLINE_SECONDS} s")
    return result
