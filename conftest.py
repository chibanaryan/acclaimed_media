"""Shared pytest fixtures."""

import ipaddress
import socket
import traceback
from pathlib import Path

import pytest

from core.tests.utils import clear_all_caches


class NetworkAccessInTests(ConnectionRefusedError):
    """A test tried to reach a host other than this machine.

    A ConnectionRefusedError, so client code meets it the way it meets a
    real outage - requests wraps it as a ConnectionError - and takes the
    same path it takes in CI, where no credentials are set.
    """


def _is_loopback(host):
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def pytest_configure(config):
    """Refuse every connection and DNS lookup that leaves this machine.

    Six modules call outside APIs (IGDB, Wikipedia, Wikidata, MusicBrainz,
    Discogs, Open Library, Hardcover). A test that forgot to patch one used
    to make the real call - from CI too - and pass or fail on whatever the
    service said that day. Loopback stays open for the Postgres job, and
    Unix sockets are untouched. Installed here rather than as a fixture so
    that setUpClass and setUpTestData are covered as well.
    """
    attempts = config._network_attempts = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    root = str(Path(__file__).resolve().parent)

    def refuse(message):
        # Recorded as well as raised: client code that swallows connection
        # errors would otherwise let the test pass without anyone knowing.
        # The project's own innermost frames say which call to patch.
        frames = [
            f"{Path(frame.filename).relative_to(root)}:{frame.lineno}"
            for frame in traceback.extract_stack()
            if frame.filename.startswith(root)
            and "/venv/" not in frame.filename
            and not frame.filename.endswith("conftest.py")
        ]
        attempts.append(f"{message} from {' <- '.join(reversed(frames[-3:]))}")
        raise NetworkAccessInTests(message)

    def check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            if not _is_loopback(str(address[0])):
                refuse(f"connect to {address!r}")

    def connect(sock, address):
        check(sock, address)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        check(sock, address)
        return real_connect_ex(sock, address)

    def getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else str(host or "")
        if not _is_loopback(name):
            refuse(f"resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


@pytest.fixture(autouse=True)
def no_network_access(request):
    """Fail any test that tried to leave the machine, even if it passed.

    The list is checked and emptied after each test, never cleared before
    one: setUpClass and setUpTestData run ahead of this fixture, so an
    attempt made there fails the class's first test instead of vanishing.
    """
    attempts = request.config._network_attempts
    yield
    if attempts:
        found = list(attempts)
        del attempts[:]
        pytest.fail(f"Test tried to reach the network: {found}")


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Start every test with every cache alias empty.

    `AnonymousResponseCacheMixin` stores rendered home/landing page responses
    in the locmem cache, which outlives the test database rollback. Without
    this, one test's rendered page can be served to another test that happens
    to share an xdist worker, which fails depending on how xdist distributes
    the tests. Both aliases are cleared because whole pages and the
    rate-limit counters live on `local` while everything else is on
    `default`; see `core.cache_config`.
    """
    clear_all_caches()
    yield
    clear_all_caches()
