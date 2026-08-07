from __future__ import annotations

import pandas as pd


def compute_regime(df: pd.DataFrame, sma_period: int = 200) -> str | None:
    """Bullish if the index's latest close is above its own SMA, else bearish.

    Returns None if there isn't enough history yet to compute the SMA.
    """
    if len(df) < sma_period:
        return None
    close = df["Close"]
    sma = close.rolling(sma_period).mean()
    if pd.isna(sma.iloc[-1]):
        return None
    return "bullish" if float(close.iloc[-1]) > float(sma.iloc[-1]) else "bearish"


def regime_series(df: pd.DataFrame, sma_period: int = 200) -> pd.Series:
    """Walk-forward regime for every bar (no lookahead - a rolling SMA only ever
    looks backward), for aligning against a ticker's own history in a backtest.
    """
    close = df["Close"]
    sma = close.rolling(sma_period).mean()
    regime = pd.Series(index=df.index, dtype=object)
    regime[close > sma] = "bullish"
    regime[close <= sma] = "bearish"
    regime[sma.isna()] = None
    return regime
