"""The network guard: a test that reaches beyond this machine fails, naming itself, the host and the remedy.

Reader: whoever writes a test that needs data from outside, or changes the wiring in tests/conftest.py.

What counts as a reach: `install()` replaces, for the whole run of the test process, the calls that
reach a host by name (`socket.getaddrinfo`, which `socket.create_connection` and urllib use), by
address (`socket.socket.connect` and `connect_ex`), and through a proxy on this machine, as in a
cloud session whose `HTTPS_PROXY` is a loopback address: `http.client.HTTPConnection.set_tunnel`
(HTTPS through a proxy) and an absolute URL given to `HTTPConnection.putrequest` (plain HTTP through
a proxy). Both proxy calls are refused before anything connects; their host is judged without its
port or IPv6 brackets (urllib passes `set_tunnel` `example.com:443` for `https://example.com:443/`).

What stays open: loopback and unspecified addresses, `localhost`, an empty or absent host, and
sockets other than IPv4 and IPv6, so the local fake servers of the suite (tests/test_ci_trust.py,
tests/test_pr_issues.py) keep working. There is no allow list: no test reaches beyond loopback.

A refused call raises `NetworkGuardError`, an `OSError`, and is recorded; `fail()` turns the report
of the test phase that made it into a failure, so a test fails even where the code under test
catches the error.

What it does not cover: it guards the test process only. Child processes reach the network
unguarded, among them git (behind its own door, scripts/git_door.py), `gh`, the clone and
`uv sync` of the session fixture `obs`, and Go builds.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import socket
import urllib.parse

OWNER = "tests/network_guard.py"
REMEDY = ("replace the call with a fake for the test, as tests/test_branch_cleanup.py does for "
          "urllib.request.urlopen, serve it from a local server as tests/test_pr_issues.py does, "
          "or read a file under tests/fixtures")


class NetworkGuardError(OSError):
    """A test tried to reach beyond this machine; the message names the test, the host and the remedy."""


_attempts: list[str] = []
_test = ["no test (collection or a session fixture)"]
_original: dict = {}


def local(host) -> bool:
    """Whether `host` (a name or an address, without a port) is this machine."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host in (None, "", "localhost"):
        return True
    try:
        address = ipaddress.ip_address(str(host).split("%")[0])
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def split_host(text: str, port=None) -> tuple[str, object]:
    """`text` as `set_tunnel` takes it (`host`, `host:port`, `[v6]` or `[v6]:port`) split into its
    host, without brackets, and its port, `port` where the text names none."""
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        return host, rest[1:] if rest.startswith(":") and rest[1:] else port
    if text.count(":") == 1:
        host, _, given = text.partition(":")
        return host, given or port
    return text, port


def _refuse(host, port) -> None:
    message = (f"{OWNER}: test {_test[-1]} reached beyond this machine, to {host}:{port}. No test "
               f"reaches the network. Remedy: {REMEDY}.")
    _attempts.append(message)
    raise NetworkGuardError(message)


def _getaddrinfo(host, port, *args, **kwargs):
    if not local(host):
        _refuse(host, port)
    return _original["getaddrinfo"](host, port, *args, **kwargs)


def _checked(name: str):
    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not local(address[0]):
            _refuse(address[0], address[1])
        return _original[name](self, address)
    return connect


def _set_tunnel(self, host, port=None, *args, **kwargs):
    name, named_port = split_host(str(host), port)
    if not local(name):
        _refuse(name, named_port if named_port is not None else self.default_port)
    return _original["set_tunnel"](self, host, port, *args, **kwargs)


def _putrequest(self, method, url, *args, **kwargs):
    if "://" in str(url):
        parts = urllib.parse.urlsplit(str(url))
        if not local(parts.hostname):
            _refuse(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    return _original["putrequest"](self, method, url, *args, **kwargs)


def install() -> None:
    """Guard this process for its whole run; installing twice changes nothing."""
    if _original:
        return
    _original.update(getaddrinfo=socket.getaddrinfo, connect=socket.socket.connect,
                     connect_ex=socket.socket.connect_ex,
                     set_tunnel=http.client.HTTPConnection.set_tunnel,
                     putrequest=http.client.HTTPConnection.putrequest)
    socket.getaddrinfo = _getaddrinfo
    socket.socket.connect = _checked("connect")
    socket.socket.connect_ex = _checked("connect_ex")
    http.client.HTTPConnection.set_tunnel = _set_tunnel
    http.client.HTTPConnection.putrequest = _putrequest


@contextlib.contextmanager
def running(test: str):
    """Name the running test in the guard's messages."""
    _test.append(test)
    try:
        yield
    finally:
        _test.pop()


def take() -> list[str]:
    """The attempts recorded since the last call; a test that provokes one takes it."""
    attempts = list(_attempts)
    _attempts.clear()
    return attempts


def fail(report) -> None:
    """Fail a test phase's report when that phase tried to reach beyond this machine."""
    attempts = take()
    if attempts:
        report.outcome = "failed"
        report.longrepr = "\n".join(attempts)
