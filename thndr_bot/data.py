from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_history(yahoo_symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    try:
        df = yf.Ticker(yahoo_symbol).history(period=period, interval=interval)
    except Exception as exc:  # network/rate-limit/etc — skip this ticker, don't crash the run
        logger.warning("Failed to fetch %s: %s", yahoo_symbol, exc)
        return None

    if df is None or df.empty:
        logger.warning("No data returned for %s", yahoo_symbol)
        return None

    return df
