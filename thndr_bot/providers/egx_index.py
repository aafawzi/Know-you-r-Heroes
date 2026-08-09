"""Official EGX index data via the exchange's own charting endpoint.

Discovered during Phase 1 discovery by reading the `egx` PyPI package's
source. It is an undocumented ASP.NET service that powers egx.com.eg's own
charts - not a published API. Two consequences drive this module's design:

1. **It is flaky.** Measured at roughly a 20-25% transient failure rate
   (4/5 successes on a fixed call; successes in ~1.2s, failures burning a
   30s timeout or resetting the connection). The whole egx.com.eg host
   behaves this way, so retry is mandatory and a single failure must never
   be reported as "no data" - that misreading is what would silently flip
   a regime engine to the wrong state.
2. **It can vanish.** No licence, no SLA, no support. Callers get an
   explicit quality status so a dead source degrades to "no signal"
   rather than "bad signal".

It returns index *values* only - no OHLC, no volume, no constituents. The
frames are shaped with a "Close" column and a DatetimeIndex so they are
drop-in compatible with the Yahoo equity frames used elsewhere.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.egx.com.eg/WebService.asmx/getIndexChartData"

# Verified against the live endpoint on 2026-08-09; every one of these
# returned data. EGX30 at period=3650 returned 2,422 daily closes back to
# 2016-08-14.
SUPPORTED_INDICES = frozenset(
    {
        "EGX30",
        "EGX30_CAP",
        "EGX30_TR",
        "EGX70_EWI",
        "EGX100_EWI",
        "EGX_33_Shariah",
        "EGXVolatility",
    }
)

# Do not "improve" these headers. This exact pair is what the `egx` PyPI
# package sends and what every successful probe used. Changing the Referer
# to https://www.egx.com.eg/ - which looks more correct - produced 4/4
# hard failures (RemoteDisconnected / ECONNRESET) against a source that
# otherwise fails only ~1 call in 4. Treat this as a working incantation
# for an undocumented endpoint, not as something to tidy.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.google.com/",
}


class Quality(str, Enum):
    """Trustworthiness of a fetch, so callers can fail safely.

    VALID   - fresh data straight from the source.
    STALE   - source unreachable; this is a cached earlier pull.
    INVALID - no usable data at all. Do not generate signals from this.
    """

    VALID = "VALID"
    STALE = "STALE"
    INVALID = "INVALID"


@dataclass
class IndexData:
    index: str
    frame: pd.DataFrame | None
    quality: Quality
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.frame is not None and not self.frame.empty


# Last good pull per (index, period). Survives only for the process, which is
# enough for a single scheduled run where the same index may be requested by
# several components.
_CACHE: dict[tuple[str, int], pd.DataFrame] = {}


def _to_frame(payload: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(payload).rename(
        columns={"CDAY": "datetime", "INDEX_VALUE": "Close"}
    )
    frame["datetime"] = pd.to_datetime(frame["datetime"])
    frame["Close"] = pd.to_numeric(frame["Close"], errors="coerce")
    # The endpoint returns newest-first; downstream indicator code assumes
    # chronological order, and getting this backwards would invert every
    # trend calculation silently.
    frame = frame.dropna(subset=["Close"]).sort_values("datetime")
    return frame.set_index("datetime")


def fetch_index(
    index: str,
    period_days: int = 3650,
    attempts: int = 4,
    timeout: int = 30,
    backoff: float = 2.0,
) -> IndexData:
    """Fetch an EGX index series, retrying through the source's flakiness.

    `period_days` is a calendar lookback; only trading days come back, so
    3650 yields roughly 2,400 rows. period_days=0 returns intraday points
    for the current session instead of daily history.
    """
    if index not in SUPPORTED_INDICES:
        raise ValueError(f"Unsupported index {index!r}. Known: {sorted(SUPPORTED_INDICES)}")

    key = (index, period_days)
    last_error = ""

    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                BASE_URL,
                params={"index": index, "period": period_days, "gtk": 0},
                headers=_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload:
                # A genuine empty response (e.g. period=0 before the open) is
                # not an error and retrying will not change it.
                return IndexData(index, pd.DataFrame(columns=["Close"]), Quality.VALID, "empty payload")

            frame = _to_frame(payload)
            _CACHE[key] = frame
            logger.info(
                "%s: %d rows %s -> %s (attempt %d)",
                index,
                len(frame),
                frame.index[0].date(),
                frame.index[-1].date(),
                attempt,
            )
            return IndexData(index, frame, Quality.VALID, f"{len(frame)} rows on attempt {attempt}")

        except Exception as exc:  # noqa: BLE001 - every failure mode here is retryable
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("%s: attempt %d/%d failed - %s", index, attempt, attempts, last_error)
            if attempt < attempts:
                time.sleep(backoff ** (attempt - 1))

    cached = _CACHE.get(key)
    if cached is not None:
        logger.warning("%s: all %d attempts failed, serving cached data", index, attempts)
        return IndexData(index, cached, Quality.STALE, f"cached; last error {last_error}")

    return IndexData(index, None, Quality.INVALID, f"all {attempts} attempts failed; {last_error}")
