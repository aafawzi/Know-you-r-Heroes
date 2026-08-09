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


def list_webservice_methods() -> None:
    """Enumerate what the official EGX WebService actually exposes.

    The .asmx help page lists every operation. Reading it beats guessing
    endpoint names, and tells us whether stock-level data, constituents or
    disclosures are reachable the same way index data is.
    """
    name = "EGX WebService method inventory"
    try:
        r = requests.get(EGX_WS, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        import re

        # First attempt anchored on a leading slash and found nothing, which I
        # wrongly recorded as "unknown" instead of retrying. Match the op
        # parameter wherever it appears so the page's actual link style
        # cannot hide the inventory again.
        methods = sorted(set(re.findall(r"op=([A-Za-z0-9_]+)", r.text)))
        line("VERIFIED", name, f"{len(methods)} operations in {len(r.text)} bytes")
        for m in methods:
            print(f"             - {m}", flush=True)
        if not methods:
            # Show what we actually got so the next attempt isn't blind.
            print("             RAW SAMPLE:", r.text[:600].replace("\n", " ")[:600], flush=True)
    except Exception as exc:  # noqa: BLE001
        line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")


def show_operation_docs(op: str) -> None:
    """Read the ASMX help page for one real operation instead of guessing its params.

    The sweep that enumerated 29 real operation names (list_webservice_methods)
    also showed that guessing endpoint names is a dead end: getStockChartData,
    getSecurityChartData etc. all 500'd or reset because none of them exist.
    GetCompanyPricesList does exist and is the obvious per-stock candidate, so
    read its own help page - ASP.NET renders one per operation with <pre>
    blocks showing the exact GET/POST/SOAP request shape, which beats guessing
    parameter names the same way listing operations beat guessing endpoints.
    """
    import re

    name = f"EGX WebService docs for {op}"
    try:
        r = requests.get(EGX_WS, params={"op": op}, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        pres = re.findall(r"<pre>(.*?)</pre>", r.text, re.S)
        line("VERIFIED", name, f"{len(pres)} <pre> blocks in {len(r.text)} bytes")
        for i, p in enumerate(pres):
            clean = re.sub(r"<[^>]+>", "", p)
            clean = clean.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
            clean = " ".join(clean.split())
            print(f"             [{i}] {clean[:400]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")


def call_string_search(op: str, prefix_text: str, count: str) -> None:
    """Call a prefixText/count ASMX operation and show what strings it actually returns.

    show_operation_docs revealed GetCompanyPricesList, GetCompanyList and
    SearchSecurities_ENG all share this exact GET signature and return
    ArrayOfString - the shape of an autocomplete/typeahead box, not a time
    series. That kills the hope of per-stock OHLCV from this operation, but
    the actual returned strings (ticker codes? "CODE - Company Name"? just
    names?) are still undetermined - call it and look, rather than assume.
    """
    name = f"EGX WebService {op} prefixText={prefix_text!r} count={count}"
    try:
        r = requests.get(
            f"{EGX_WS}/{op}",
            params={"prefixText": prefix_text, "count": count},
            headers=UA,
            timeout=TIMEOUT,
        )
        if not r.ok:
            line("FAILED", name, f"HTTP {r.status_code}")
            return
        import re

        items = re.findall(r"<string>(.*?)</string>", r.text)
        line("VERIFIED", name, f"{len(items)} items | {items[:15]}")
    except Exception as exc:  # noqa: BLE001
        line("FAILED", name, f"{type(exc).__name__}: {str(exc)[:110]}")


def reliability_check(index: str, period: int, attempts: int = 5) -> None:
    """Quantify the intermittent connection resets seen on this endpoint.

    Successes returned in ~1.5s while failures hung ~28s before a reset,
    which looks like throttling rather than a bad parameter. If that's
    right, a retry with backoff makes the source usable; if the failures
    are deterministic per-parameter, it doesn't.
    """
    name = f"Reliability {index} p={period} x{attempts}"
    ok = 0
    timings = []
    import time as _t

    for _ in range(attempts):
        t0 = _t.monotonic()
        try:
            r = requests.get(
                f"{EGX_WS}/getIndexChartData",
                params={"index": index, "period": period, "gtk": 0},
                headers=UA,
                timeout=TIMEOUT,
            )
            rows = len(r.json()) if r.ok else 0
            if rows:
                ok += 1
            timings.append(f"{_t.monotonic()-t0:.1f}s/{rows}r")
        except Exception:  # noqa: BLE001
            timings.append(f"{_t.monotonic()-t0:.1f}s/ERR")
        _t.sleep(2)
    line("VERIFIED" if ok else "FAILED", name, f"{ok}/{attempts} ok | {timings}")


def main() -> None:
    print(f"EGX data-source probe @ {datetime.now(timezone.utc).isoformat()}\n")

    print("--- 0. Official EGX WebService: what exists ---")
    list_webservice_methods()
    # Sweep 3 (run 31319670642) confirmed the previous guessed endpoint names
    # (getStockChartData etc.) do not exist - all six 500'd or reset. The real
    # inventory names a genuine per-stock candidate, GetCompanyPricesList, plus
    # a listed-companies operation and a security search. Read their help pages
    # for the real parameter contract rather than guessing again.
    for op in (
        "GetCompanyPricesList",
        "GetCompanyList",
        "getIndexData",
        "SearchSecurities_ENG",
        "GetInvestorTables",
    ):
        show_operation_docs(op)
    # All three prefixText/count operations returned an ArrayOfString GET
    # contract - the shape of an autocomplete box, not a time series. Call
    # them with a real prefix to see what content they actually hold before
    # concluding they are useless for per-stock OHLCV.
    for op in ("GetCompanyPricesList", "GetCompanyList", "SearchSecurities_ENG"):
        call_string_search(op, "COM", "10")
    reliability_check("EGX30", 365)
    head(
        "https://www.egx.com.eg/en/currentindexconstituntes.aspx?type=22&nav=22",
        "EGX 33 Shariah constituents page",
    )
    head(
        "https://www.egx.com.eg/en/currentindexconstituntes.aspx?type=1&nav=1",
        "EGX 30 constituents page",
    )


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
