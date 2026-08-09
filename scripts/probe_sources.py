"""Probe candidate EGX data sources and report what is actually reachable.

Run this from CI, not from a dev container: the container's egress proxy
only allows an allowlist (GitHub/PyPI/npm), so every external host 403s at
the CONNECT tunnel and every result would be a false negative.

The point of this script is to replace "the docs say it works" with
evidence. It prints one line per probe with a VERIFIED / FAILED verdict
and enough detail (row counts, date ranges, field names) to design
against. Nothing here is cached or committed - re-run it whenever a
source's status is in question, because these are third-party endpoints
that can disappear without notice.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone

import requests

TIMEOUT = 30
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.google.com/",
}

EGX_WS = "https://www.egx.com.eg/WebService.asmx"


def line(status: str, name: str, detail: str = "") -> None:
    print(f"[{status:<8}] {name:<52} {detail}", flush=True)


def probe(name: str):
    """Decorator-ish helper: run fn, catch everything, never abort the sweep."""

    def run(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a probe failing is a result, not a crash
            line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")
        return fn

    return run


def head(url: str, name: str) -> None:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        detail = f"HTTP {r.status_code}, {len(r.content)} bytes, ct={r.headers.get('content-type','?')[:40]}"
        line("VERIFIED" if r.ok else "FAILED", name, detail)
    except Exception as exc:  # noqa: BLE001
        line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")


def egx_index(index: str, period: int) -> None:
    name = f"EGX WebService getIndexChartData {index} p={period}"
    try:
        r = requests.get(
            f"{EGX_WS}/getIndexChartData",
            params={"index": index, "period": period, "gtk": 0},
            headers=UA,
            timeout=TIMEOUT,
        )
        if not r.ok:
            line("FAILED", name, f"HTTP {r.status_code}")
            return
        data = r.json()
        if not data:
            line("EMPTY", name, "200 but zero rows (market closed / no history?)")
            return
        keys = sorted(data[0].keys())
        first, last = data[0].get("CDAY"), data[-1].get("CDAY")
        line("VERIFIED", name, f"{len(data)} rows | {first} -> {last} | fields={keys}")
    except Exception as exc:  # noqa: BLE001
        line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")


def yahoo_chart(symbol: str, rng: str) -> None:
    name = f"Yahoo chart {symbol} range={rng}"
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": rng, "interval": "1d"},
            headers=UA,
            timeout=TIMEOUT,
        )
        payload = r.json()
        err = (payload.get("chart") or {}).get("error")
        if err:
            line("FAILED", name, f"HTTP {r.status_code} | {str(err)[:100]}")
            return
        res = payload["chart"]["result"][0]
        ts = res.get("timestamp") or []
        if not ts:
            line("EMPTY", name, f"HTTP {r.status_code} | 0 bars")
            return
        f = datetime.fromtimestamp(ts[0], timezone.utc).date()
        l = datetime.fromtimestamp(ts[-1], timezone.utc).date()
        quote = (res.get("indicators", {}).get("quote") or [{}])[0]
        have = [k for k in ("open", "high", "low", "close", "volume") if quote.get(k)]
        cur = res.get("meta", {}).get("currency")
        line("VERIFIED", name, f"{len(ts)} bars | {f} -> {l} | {have} | {cur}")
    except Exception as exc:  # noqa: BLE001
        line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")


def main() -> None:
    print(f"EGX data-source probe @ {datetime.now(timezone.utc).isoformat()}\n")

    print("--- 1. Official EGX WebService (indices) ---")
    # period=0 is intraday-today; the long lookbacks are what a regime engine
    # and any index benchmark actually need.
    for period in (0, 365, 1825, 3650):
        egx_index("EGX30", period)
    for idx in ("EGX70_EWI", "EGX100_EWI", "EGX_33_Shariah", "EGX30_CAP", "EGXVolatility"):
        egx_index(idx, 365)

    print("\n--- 2. Official EGX site surfaces ---")
    head(EGX_WS, "EGX WebService.asmx method list")
    head("https://www.egx.com.eg", "egx.com.eg homepage")
    head("https://www.egx.com.eg/en/homepage.aspx", "egx.com.eg EN homepage")

    print("\n--- 3. Yahoo Finance: EGX equities ---")
    for sym in ("COMI.CA", "SWDY.CA", "ETEL.CA", "TMGH.CA", "ISPH.CA", "GOUR.CA", "BONY.CA"):
        yahoo_chart(sym, "2y")

    print("\n--- 4. Yahoo Finance: EGX indices (known-weak) ---")
    for sym in ("^CASE30", "^EGX30.CA", "EGX30.CA"):
        for rng in ("5d", "2y"):
            yahoo_chart(sym, rng)

    print("\n--- 5. Third-party surfaces (reachability only) ---")
    head("https://www.mubasher.info/countries/eg", "Mubasher Egypt")
    head("https://www.investing.com/indices/egx-30-historical-data", "Investing.com EGX30")
    head("https://fra.gov.eg", "FRA (regulator)")
    head("https://www.cbe.org.eg", "CBE (central bank)")
    head("https://www.eodhd.com", "EODHD (commercial)")
    head("https://twelvedata.com", "Twelve Data (commercial)")

    print("\nDone. VERIFIED = reachable and returned usable shape; FAILED/EMPTY = do not design around it.")


if __name__ == "__main__":
    main()
