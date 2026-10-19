import itertools
import time
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest
from fake_curl import Curl, answer

from cheevos.core.clock import ServerClock
from cheevos.core.errors import NetworkError
from cheevos.core.ra_client.common import API_HOST, MEDIA_HOST, Response
from cheevos.platform import curl_transport
from cheevos.platform.curl_transport import CurlTransport

GAMEID = "/dorequest.php?r=gameid&m=" + "1" * 32
RA_DATE = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class Fallback:
    def __init__(self):
        self.created = 0
        self.requests = []

    def __call__(self):
        self.created += 1
        return self

    def get(self, host, path, headers):
        self.requests.append((host, path))
        return Response(status=200, body=b"from python")


@pytest.fixture
def curl(tmp_path):
    return Curl(tmp_path)


@pytest.fixture
def fallback():
    return Fallback()


@pytest.fixture
def clock():
    return ServerClock(wall_clock=lambda: 0.0, monotonic=lambda: 100.0)


@pytest.fixture
def transport(curl, fallback, clock, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    return CurlTransport(str(curl.path), fallback, timeout=15, server_clock=clock)


def test_an_answer_keeps_its_status_body_and_date(curl, transport, clock):
    date = format_datetime(RA_DATE, usegmt=True)
    curl.plan(answer('{"Success":true,"GameID":1479}', date=date))

    response = transport.get(API_HOST, GAMEID, {})

    assert response == Response(
        status=200, headers={"date": date}, body=b'{"Success":true,"GameID":1479}'
    )
    assert clock.now() == RA_DATE.timestamp()  # RA's Date sets the app's clock


def test_only_the_api_host_sets_the_clock(curl, transport, clock):
    curl.plan(answer("x", date=format_datetime(RA_DATE, usegmt=True)))

    transport.get(MEDIA_HOST, "/Images/1.png", {})

    assert clock.now() == 0.0


@pytest.mark.parametrize("body", ["", "line\nbreaks\n", "\n\n", '{"a": "\\n"}'])
def test_the_body_is_returned_as_sent(curl, transport, body):
    curl.plan(answer(body))
    assert transport.get(API_HOST, GAMEID, {}).body == body.encode()


def test_http_errors_are_answers_not_failures(curl, transport):
    curl.plan(answer("<html>busy</html>", status=503))
    assert transport.get(API_HOST, GAMEID, {}).status == 503


def test_the_request(curl, transport, monkeypatch, tmp_path):
    bundle = tmp_path / "ca-certificates.crt"
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    curl.plan(answer("{}"))

    transport.get(API_HOST, GAMEID, {"User-Agent": "Cheevos/test", "Accept": "application/json"})

    (arguments,) = curl.calls
    assert arguments[0] == "--disable"  # no ~/.curlrc
    assert arguments[-1] == f"https://{API_HOST}{GAMEID}"
    pairs = list(itertools.pairwise(arguments))
    assert ("--cacert", str(bundle)) in pairs
    assert ("--header", "User-Agent: Cheevos/test") in pairs
    assert ("--header", "Accept: application/json") in pairs
    assert ("--max-time", "15") in pairs
    assert ("--noproxy", "*") in pairs
    # Never skip certificate checks or follow redirects.
    assert not {"-k", "--insecure", "-L", "--location"} & set(arguments)


def test_without_a_bundle_curl_uses_its_own(curl, transport):
    curl.plan(answer("{}"))
    transport.get(API_HOST, GAMEID, {})
    assert "--cacert" not in curl.calls[0]


@pytest.mark.parametrize("code", sorted(curl_transport.TLS_FAILURES))
def test_tls_failure_on_ra_retries_over_http_and_stays_there(curl, transport, code):
    curl.plan({"code": code, "stderr": "curl: certificate is not yet valid"}, answer("{}"))

    assert transport.get(API_HOST, GAMEID, {}).status == 200
    assert transport.get(API_HOST, GAMEID, {}).status == 200

    assert curl.urls == [f"https://{API_HOST}{GAMEID}"] + [f"http://{API_HOST}{GAMEID}"] * 2
    assert "--cacert" not in curl.calls[1]


def test_tls_failure_elsewhere_is_a_network_error(curl, transport):
    curl.plan({"code": 60})
    with pytest.raises(NetworkError, match=r"example\.org"):
        transport.get("example.org", "/", {})
    assert len(curl.calls) == 1


@pytest.mark.parametrize("code", sorted(curl_transport.NETWORK_FAILURES))
def test_network_failures_are_network_errors(curl, transport, fallback, code):
    curl.plan({"code": code, "stderr": "curl: (6) Could not resolve host"})

    with pytest.raises(NetworkError, match=f"curl {code}: curl: .6. Could not resolve host"):
        transport.get(API_HOST, GAMEID, {})
    assert fallback.created == 0  # offline is offline: Python would fail the same way


@pytest.mark.parametrize(
    "step",
    [
        {"code": 2, "stderr": "curl: (2) Failed initialization"},
        {"code": 43},
        {"code": 127, "stderr": "error while loading shared libraries"},
        {"stdout": "no write-out"},
        {"stdout": "{}\n000\n"},
        {"stdout": "{}\nabc\n"},
    ],
)
def test_a_broken_curl_falls_back_to_python_for_good(curl, transport, fallback, step, caplog):
    curl.plan(step)

    assert transport.get(API_HOST, GAMEID, {}).body == b"from python"
    assert transport.get(API_HOST, GAMEID, {}).body == b"from python"

    assert len(curl.calls) == 1
    assert fallback.created == 1
    assert fallback.requests == [(API_HOST, GAMEID)] * 2
    assert "using Python's HTTPS" in caplog.text


@pytest.mark.parametrize("problem", ["missing", "not executable", "not a program"])
def test_a_curl_that_cannot_run_falls_back_to_python(tmp_path, fallback, problem):
    path = tmp_path / "curl"
    if problem != "missing":
        path.write_bytes(b"\x7fELF\x01\x01\x01" if problem == "not a program" else b"#!/bin/sh\n")
        path.chmod(0o755 if problem == "not a program" else 0o644)

    transport = CurlTransport(str(path), fallback, timeout=15)

    assert transport.get(API_HOST, GAMEID, {}).body == b"from python"


def test_a_curl_that_hangs_is_killed_and_offline(curl, fallback, monkeypatch):
    monkeypatch.setattr(curl_transport, "KILL_GRACE", 0.2)
    curl.plan({"sleep": 30})
    transport = CurlTransport(str(curl.path), fallback, timeout=0.1)

    started = time.monotonic()
    with pytest.raises(NetworkError, match="in time"):
        transport.get(API_HOST, GAMEID, {})

    assert time.monotonic() - started < 10
    assert fallback.created == 0
