from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import STRATEGY, StrategyConfig


@dataclass
class Signal:
    action: str  # "BUY", "SELL", "HOLD"
    price: float
    sma_fast: float
    sma_slow: float
    rsi: float


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_signal(df: pd.DataFrame, cfg: StrategyConfig | None = None) -> Signal | None:
    cfg = cfg or STRATEGY

    if len(df) < cfg.sma_slow + 2:
        return None

    close = df["Close"]
    sma_fast = close.rolling(cfg.sma_fast).mean()
    sma_slow = close.rolling(cfg.sma_slow).mean()
    rsi = _rsi(close, cfg.rsi_period)

    if pd.isna(sma_fast.iloc[-1]) or pd.isna(sma_slow.iloc[-1]) or pd.isna(rsi.iloc[-1]):
        return None

    prev_diff = sma_fast.iloc[-2] - sma_slow.iloc[-2]
    curr_diff = sma_fast.iloc[-1] - sma_slow.iloc[-1]

    action = "HOLD"
    # Golden cross: fast SMA crosses above slow SMA, and we're not already overbought.
    if prev_diff <= 0 and curr_diff > 0 and rsi.iloc[-1] < cfg.rsi_overbought:
        action = "BUY"
    # Death cross: fast SMA crosses below slow SMA, and we're not already oversold.
    elif prev_diff >= 0 and curr_diff < 0 and rsi.iloc[-1] > cfg.rsi_oversold:
        action = "SELL"

    return Signal(
        action=action,
        price=float(close.iloc[-1]),
        sma_fast=float(sma_fast.iloc[-1]),
        sma_slow=float(sma_slow.iloc[-1]),
        rsi=float(rsi.iloc[-1]),
    )
