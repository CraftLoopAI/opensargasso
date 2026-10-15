"""Fetching: which errors are retried, a blocked host is skipped, and the server's reason is kept."""
import datetime as dt
import io
import json
import urllib.error

import pytest

from pipeline import erddap, probe, rerun

URL = "https://data.example.org/erddap/griddap/ds.csv"


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError(URL, code, "", headers or {}, io.BytesIO(body))


def scripted(monkeypatch, *outcomes):
    """Make urlopen raise or answer from `outcomes` in turn; returns the list of calls."""
    calls = []

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout):
        calls.append(timeout)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return Answer(outcome)

    monkeypatch.setattr(erddap.urllib.request, "urlopen", fake)
    return calls


def test_403_is_a_blocked_host_with_the_reason_and_no_retry(monkeypatch):
    calls = scripted(monkeypatch, http_error(403, b"<html> Your IP address is on this ERDDAP's request blacklist </html>"))
    with pytest.raises(erddap.HostBlocked, match="data.example.org: <html> Your IP address is on this ERDDAP's request blacklist"):
        erddap.fetch_bytes(URL, sleep=lambda s: None)
    assert len(calls) == 1


def test_other_4xx_raise_at_once_and_keep_the_reason(monkeypatch):
    calls = scripted(monkeypatch, http_error(404, b"Error { code=404; message=\"Your query produced no matching results.\" }"))
    with pytest.raises(urllib.error.HTTPError) as e:
        erddap.fetch_bytes(URL, sleep=lambda s: None)
    assert e.value.code == 404 and "no matching results" in str(e.value) and len(calls) == 1


def test_timeouts_429_and_5xx_are_retried_with_growing_waits(monkeypatch):
    calls = scripted(monkeypatch, TimeoutError("timed out"), http_error(429), http_error(503), b"ok")
    waits = []
    assert erddap.fetch_bytes(URL, sleep=waits.append) == b"ok"
    assert len(calls) == 4 and calls[0] == 90
    assert [round(w / base, 2) <= 1.25 and w >= base for w, base in zip(waits, erddap.RETRY_WAITS)] == [True] * 3


def test_a_dataset_that_is_reloading_is_retried(monkeypatch):
    reloading = b'Error { code=404; message="Not Found: Currently unknown datasetID=ncep_global_lon180"; }'
    calls = scripted(monkeypatch, http_error(404, reloading), b"ok")
    assert erddap.fetch_bytes(URL, sleep=lambda s: None) == b"ok" and len(calls) == 2


def test_retry_after_is_honored_and_the_last_error_is_reported(monkeypatch):
    scripted(monkeypatch, http_error(429, headers={"Retry-After": "200"}), http_error(500, b"oops"), http_error(500, b"oops"), http_error(500, b"oops"))
    waits = []
    with pytest.raises(RuntimeError, match="HTTP 500 oops"):
        erddap.fetch_bytes(URL, sleep=waits.append)
    assert waits[0] >= 200 and len(waits) == 3


def test_retries_stop_at_the_deadline(monkeypatch):
    calls = scripted(monkeypatch, TimeoutError("timed out"), TimeoutError("timed out"))
    with pytest.raises(RuntimeError, match="timed out"):
        erddap.fetch_bytes(URL, deadline=erddap._time.monotonic() + 5, sleep=lambda s: None)   # a 20 s wait would pass it
    assert len(calls) == 1


def test_second_run_only_when_the_first_had_no_fresh_wind(tmp_path):
    today = dt.date(2026, 10, 15)
    assert rerun.needed(tmp_path, today)[0] is True                                   # no run yet today
    for wind, go in (("forecast", False), ("cached", True), ("constant", True)):
        (tmp_path / "2026-10-15.json").write_text(json.dumps({"date": "2026-10-15", "wind": wind}))
        assert rerun.needed(tmp_path, today)[0] is go, wind
    (tmp_path / "2026-10-15.json").write_text("{not json")
    assert rerun.needed(tmp_path, today)[0] is True


def test_probe_reports_answers_refusals_and_silence():
    class Answer(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert probe.check(URL, opener=lambda req, timeout: Answer(b"time,latitude\n UTC"))[::2] == (200, "time,latitude UTC")

    def refuse(req, timeout):
        raise http_error(403, b"blacklist")

    def silent(req, timeout):
        raise urllib.error.URLError(TimeoutError("timed out"))

    assert probe.check(URL, opener=refuse)[::2] == (403, "blacklist")
    assert probe.check(URL, opener=silent)[0] == "no answer"
    labels = [label for label, _ in probe.candidates()]
    assert labels[0].startswith("wind: UCAR") and any("NHC" in label for label in labels)
