import pandas as pd
import pytest

from thndr_bot.providers import egx_index
from thndr_bot.providers.egx_index import Quality, fetch_index

# Endpoint returns newest-first, which is the ordering trap this module has to
# undo. Values chosen so a sort bug is visible in the assertions.
_PAYLOAD = [
    {"CDAY": "2026-08-06T00:00:00", "INDEX_VALUE": 30000.0},
    {"CDAY": "2026-08-05T00:00:00", "INDEX_VALUE": 29000.0},
    {"CDAY": "2026-08-04T00:00:00", "INDEX_VALUE": 28000.0},
]


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    egx_index._CACHE.clear()
    yield
    egx_index._CACHE.clear()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Backoff would otherwise make the retry tests take seconds.
    monkeypatch.setattr(egx_index.time, "sleep", lambda _s: None)


def test_rejects_unknown_index_before_making_a_request():
    with pytest.raises(ValueError, match="Unsupported index"):
        fetch_index("NOT_AN_INDEX")


def test_returns_chronological_frame_with_close_column(monkeypatch):
    monkeypatch.setattr(egx_index.requests, "get", lambda *a, **k: _Response(_PAYLOAD))

    result = fetch_index("EGX30")

    assert result.quality is Quality.VALID
    assert result.usable
    # Sorted oldest-first despite the newest-first payload.
    assert list(result.frame["Close"]) == [28000.0, 29000.0, 30000.0]
    assert result.frame.index[0] < result.frame.index[-1]


def test_retries_through_transient_failure_then_succeeds(monkeypatch):
    # Mirrors the measured behaviour: first call dies, later calls are fine.
    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError(104, "Connection reset by peer")
        return _Response(_PAYLOAD)

    monkeypatch.setattr(egx_index.requests, "get", flaky)

    result = fetch_index("EGX30", attempts=4)

    assert result.quality is Quality.VALID
    assert calls["n"] == 3


def test_serves_cached_data_as_stale_when_source_dies(monkeypatch):
    monkeypatch.setattr(egx_index.requests, "get", lambda *a, **k: _Response(_PAYLOAD))
    first = fetch_index("EGX30")
    assert first.quality is Quality.VALID

    def always_fails(*_a, **_k):
        raise ConnectionResetError(104, "Connection reset by peer")

    monkeypatch.setattr(egx_index.requests, "get", always_fails)
    second = fetch_index("EGX30", attempts=2)

    # Degrades to STALE rather than pretending there is no data - but is
    # honest about it so callers can refuse to act.
    assert second.quality is Quality.STALE
    assert second.usable
    assert list(second.frame["Close"]) == [28000.0, 29000.0, 30000.0]


def test_reports_invalid_when_there_is_no_cache_to_fall_back_on(monkeypatch):
    def always_fails(*_a, **_k):
        raise ConnectionResetError(104, "Connection reset by peer")

    monkeypatch.setattr(egx_index.requests, "get", always_fails)

    result = fetch_index("EGX30", attempts=3)

    assert result.quality is Quality.INVALID
    assert not result.usable
    assert result.frame is None
    assert "3 attempts" in result.detail


def test_empty_payload_is_valid_not_an_error(monkeypatch):
    # period=0 before the market opens legitimately returns nothing; retrying
    # would waste a 30s timeout per attempt for no reason.
    calls = {"n": 0}

    def empty(*_a, **_k):
        calls["n"] += 1
        return _Response([])

    monkeypatch.setattr(egx_index.requests, "get", empty)

    result = fetch_index("EGX30", period_days=0, attempts=4)

    assert result.quality is Quality.VALID
    assert not result.usable
    assert calls["n"] == 1


def test_drops_unparseable_values_rather_than_poisoning_the_series(monkeypatch):
    payload = _PAYLOAD + [{"CDAY": "2026-08-03T00:00:00", "INDEX_VALUE": None}]
    monkeypatch.setattr(egx_index.requests, "get", lambda *a, **k: _Response(payload))

    result = fetch_index("EGX30")

    assert len(result.frame) == 3
    assert result.frame["Close"].notna().all()


def test_frame_is_shaped_like_the_yahoo_frames_regime_already_consumes(monkeypatch):
    from thndr_bot.regime import compute_regime

    monkeypatch.setattr(egx_index.requests, "get", lambda *a, **k: _Response(_PAYLOAD))
    result = fetch_index("EGX30")

    # The whole point of the "Close" + DatetimeIndex shape: existing regime
    # code consumes it unchanged.
    assert compute_regime(result.frame, sma_period=2) == "bullish"
    assert isinstance(result.frame.index, pd.DatetimeIndex)
