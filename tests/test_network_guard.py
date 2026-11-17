"""The network guard (tests/network_guard.py): what it refuses, what stays open, and that a caught
attempt still fails its test."""

from __future__ import annotations

import http.client
import socket
from types import SimpleNamespace

import pytest

import network_guard


def refused(request: pytest.FixtureRequest, error: pytest.ExceptionInfo, target: str) -> None:
    """`error` names the running test, the host and port, and the remedy; the test takes its attempt."""
    message = str(error.value)
    assert request.node.nodeid in message
    assert target in message
    assert network_guard.REMEDY in message
    assert network_guard.take() == [message]


def test_a_connection_by_address_beyond_this_machine_is_refused(request):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(network_guard.NetworkGuardError) as error:
            client.connect(("192.0.2.1", 9))
    refused(request, error, "192.0.2.1:9")


def test_a_connect_ex_beyond_this_machine_is_refused(request):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(network_guard.NetworkGuardError) as error:
            client.connect_ex(("192.0.2.1", 9))
    refused(request, error, "192.0.2.1:9")


def test_a_lookup_of_a_name_is_refused(request):
    with pytest.raises(network_guard.NetworkGuardError) as error:
        socket.getaddrinfo("example.invalid", 443)
    refused(request, error, "example.invalid:443")


def test_a_loopback_server_stays_reachable():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=5) as client:
            peer, _ = server.accept()
            with peer:
                client.sendall(b"ping")
                assert peer.recv(4) == b"ping"
        socket.getaddrinfo("localhost", None)
    assert network_guard.take() == []


@pytest.mark.parametrize(("call", "target"), [
    (lambda connection: connection.set_tunnel("192.0.2.1"), "192.0.2.1:80"),
    (lambda connection: connection.set_tunnel("example.invalid:443"), "example.invalid:443"),
    (lambda connection: connection.set_tunnel("[2001:db8::1]:8443"), "2001:db8::1:8443"),
    (lambda connection: connection.putrequest("GET", "http://192.0.2.1/"), "192.0.2.1:80"),
], ids=["tunnel-by-address", "tunnel-with-port", "tunnel-v6", "absolute-url"])
def test_a_request_through_a_local_proxy_is_refused_before_it_connects(request, call, target):
    connection = http.client.HTTPConnection("127.0.0.1", 9)
    with pytest.raises(network_guard.NetworkGuardError) as error:
        call(connection)
    assert connection.sock is None
    refused(request, error, target)


@pytest.mark.parametrize("host", ["localhost", "localhost:8080", "127.0.0.1:3128", "[::1]:8080"])
def test_a_tunnel_to_this_machine_stays_open(host):
    connection = http.client.HTTPConnection("127.0.0.1", 9)
    connection.set_tunnel(host)
    assert connection.sock is None
    assert network_guard.take() == []


def test_a_caught_attempt_still_fails_its_phase():
    try:
        socket.getaddrinfo("example.invalid", 80)
    except OSError:
        pass  # the code under test swallows it
    report = SimpleNamespace(outcome="passed", longrepr=None)
    network_guard.fail(report)
    assert report.outcome == "failed"
    assert "example.invalid:80" in report.longrepr
    clean = SimpleNamespace(outcome="passed", longrepr=None)
    network_guard.fail(clean)
    assert clean.outcome == "passed"
