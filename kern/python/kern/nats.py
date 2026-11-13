"""A NATS peer on the standard library: ``CONNECT``, ``SUB``, ``PUB`` and request/reply.

The core's bus is a NATS server on loopback (SE's docs/go-core.md, "How a
component in another language attaches"). This peer speaks the part of NATS's
text protocol a component needs: it connects with its user and password, keeps
one reader thread that answers the server's ``PING`` and hands each ``MSG`` to its
subscription's handler, and asks with a reply subject in its own inbox, which
the bus lets it hear. No reconnect: a new core stands a new bus.
"""

from __future__ import annotations

import itertools
import json
import secrets
import socket
import threading
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from .subjects import inbox


class NatsError(Exception):
    """The server refused something, or the connection is gone."""


@dataclass(frozen=True)
class Msg:
    subject: str
    reply: str
    data: bytes

    def json(self):
        return json.loads(self.data) if self.data else None


Handler = Callable[[Msg], None]


class Peer:
    """One connection to the bus as one user."""

    def __init__(self, url: str, user: str, password: str, *, name: str = "kern-python", timeout: float = 2.0):
        u = urlparse(url if "://" in url else "nats://" + url)
        self.user = user
        self._sock = socket.create_connection((u.hostname or "127.0.0.1", u.port or 4222), timeout=timeout)
        self._file = self._sock.makefile("rb")
        self._lock = threading.Lock()
        self._sids = itertools.count(1)
        self._subs: dict[int, Handler] = {}
        self._waiting: dict[str, tuple[threading.Event, list[Msg]]] = {}
        self._progress: dict[str, Handler] = {}
        self._next = itertools.count(1)
        self._inbox = inbox(user) + "." + secrets.token_hex(8)
        #: The errors the server sent, such as a permissions violation; `closed` is set once the connection is gone.
        self.errors: list[str] = []
        self.closed = threading.Event()
        self._pong: threading.Event | None = None
        line = self._file.readline()
        if not line.startswith(b"INFO "):
            raise NatsError(f"bus at {url} answers {line!r}, not INFO")
        connect = {"verbose": False, "pedantic": False, "user": user, "pass": password, "name": name,
                   "lang": "python", "version": "kern", "protocol": 1, "echo": True, "headers": False}
        self._send(b"CONNECT " + json.dumps(connect).encode() + b"\r\nPING\r\n")
        while True:
            line = self._file.readline()
            if line.startswith(b"PONG"):
                break
            if line.startswith(b"-ERR") or not line:
                self._sock.close()
                raise NatsError(f"bus at {url} refuses {user}: {line.decode(errors='replace').strip()}")
        self._sock.settimeout(None)
        self._sub_raw(self._inbox + ".*", self._answered)
        self._reader = threading.Thread(target=self._read, name="kern-nats", daemon=True)
        self._reader.start()

    def _send(self, data: bytes) -> None:
        with self._lock:
            try:
                self._sock.sendall(data)
            except OSError as e:
                raise NatsError(f"the bus is gone: {e}") from None

    def _sub_raw(self, subject: str, handler: Handler) -> int:
        sid = next(self._sids)
        self._subs[sid] = handler
        self._send(f"SUB {subject} {sid}\r\n".encode())
        return sid

    def subscribe(self, subject: str, handler: Handler) -> int:
        """Hand every message on subject to handler, on the reader thread: a handler that asks hands off first."""
        return self._sub_raw(subject, handler)

    def unsubscribe(self, sid: int) -> None:
        self._subs.pop(sid, None)
        self._send(f"UNSUB {sid}\r\n".encode())

    def publish(self, subject: str, data: bytes | str | dict | list = b"", reply: str = "") -> None:
        if isinstance(data, (dict, list)):
            data = json.dumps(data)
        if isinstance(data, str):
            data = data.encode()
        head = f"PUB {subject} {reply} {len(data)}\r\n" if reply else f"PUB {subject} {len(data)}\r\n"
        self._send(head.encode() + data + b"\r\n")

    def request(self, subject: str, data: bytes | str | dict | list = b"", timeout: float = 10.0) -> Msg:
        """Publish with a reply subject in this peer's inbox and wait for the one answer."""
        reply = f"{self._inbox}.{next(self._next)}"
        got: tuple[threading.Event, list[Msg]] = (threading.Event(), [])
        self._waiting[reply] = got
        try:
            self.publish(subject, data, reply)
            if not got[0].wait(timeout) or not got[1]:
                if self.closed.is_set():
                    raise NatsError(f"the bus closed before {subject} answered")
                raise NatsError(f"{subject} answers nothing within {timeout} s")
            return got[1][0]
        finally:
            self._waiting.pop(reply, None)

    def call(self, subject: str, body: dict, on_progress: Handler, idle: float = 60.0) -> Msg:
        """Ask a streaming call, ``call.<command>``: name a progress subject in this peer's inbox in
        the body, hand each progress message (``{"line"}`` or ``{"beat"}``) to on_progress as it
        comes, and wait for the one answer as long as the core says anything within ``idle``
        seconds (docs/go-core.md "Progress and long calls")."""
        n = next(self._next)
        reply, progress = f"{self._inbox}.{n}", f"{self._inbox}.p{n}"
        got: tuple[threading.Event, list[Msg]] = (threading.Event(), [])
        heard = threading.Event()

        def said(msg: Msg) -> None:
            heard.set()
            on_progress(msg)

        self._waiting[reply] = got
        self._progress[progress] = said
        try:
            self.publish(subject, {**body, "progress": progress}, reply)
            while not got[0].is_set():
                heard.clear()
                if got[0].wait(idle) or heard.is_set():
                    continue
                raise NatsError(f"{subject} says nothing within {idle} s")
            if not got[1]:
                raise NatsError(f"the bus closed before {subject} answered")
            return got[1][0]
        finally:
            self._waiting.pop(reply, None)
            self._progress.pop(progress, None)

    def respond(self, msg: Msg, data: bytes | str | dict | list) -> None:
        if msg.reply:
            self.publish(msg.reply, data)

    def flush(self, timeout: float = 5.0) -> None:
        """Wait until the server has read everything sent so far."""
        self._pong = threading.Event()
        self._send(b"PING\r\n")
        if not self._pong.wait(timeout):
            raise NatsError("the bus answers no PING")

    def close(self) -> None:
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        self.closed.wait(2)

    def _answered(self, msg: Msg) -> None:
        said = self._progress.get(msg.subject)
        if said:
            said(msg)
            return
        got = self._waiting.get(msg.subject)
        if got:
            got[1].append(msg)
            got[0].set()

    def _read(self) -> None:
        f = self._file
        try:
            while True:
                line = f.readline()
                if not line:
                    break
                if line.startswith(b"MSG "):
                    parts = line.split()
                    subject, sid, size = parts[1].decode(), int(parts[2]), int(parts[-1])
                    reply = parts[3].decode() if len(parts) == 5 else ""
                    data = f.read(size + 2)[:size]
                    handler = self._subs.get(sid)
                    if handler:
                        try:
                            handler(Msg(subject, reply, data))
                        except Exception as e:  # a handler's failure leaves the connection standing
                            self.errors.append(f"handler of {subject}: {e}")
                elif line.startswith(b"PING"):
                    self._send(b"PONG\r\n")
                elif line.startswith(b"PONG"):
                    if self._pong:
                        self._pong.set()
                elif line.startswith(b"-ERR"):
                    self.errors.append(line[5:].decode(errors="replace").strip().strip("'"))
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()
            for ev, _ in list(self._waiting.values()):
                ev.set()
