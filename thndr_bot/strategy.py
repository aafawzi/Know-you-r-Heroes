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
    macd: float
    macd_signal: float
    confluence: int  # how many of {RSI, MACD, volume, Bollinger} confirmed, out of 4
    confluence_required: int


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int, slow: int, signal_period: int) -> tuple[pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    return macd_line, signal_line


def _bollinger_bands(close: pd.Series, period: int, num_std: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid + num_std * std, mid, mid - num_std * std


def compute_signal(df: pd.DataFrame, cfg: StrategyConfig | None = None) -> Signal | None:
    cfg = cfg or STRATEGY

    min_bars = max(cfg.sma_slow, cfg.macd_slow + cfg.macd_signal_period, cfg.bb_period, cfg.volume_avg_period) + 2
    if len(df) < min_bars:
        return None

    close = df["Close"]
    volume = df["Volume"] if "Volume" in df.columns else None

    sma_fast = close.rolling(cfg.sma_fast).mean()
    sma_slow = close.rolling(cfg.sma_slow).mean()
    rsi = _rsi(close, cfg.rsi_period)
    macd_line, macd_signal_line = _macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal_period)
    bb_upper, bb_mid, bb_lower = _bollinger_bands(close, cfg.bb_period, cfg.bb_std)

    if any(pd.isna(s.iloc[-1]) for s in (sma_fast, sma_slow, rsi, macd_line, macd_signal_line, bb_mid)):
        return None

    prev_diff = sma_fast.iloc[-2] - sma_slow.iloc[-2]
    curr_diff = sma_fast.iloc[-1] - sma_slow.iloc[-1]
    golden_cross = prev_diff <= 0 and curr_diff > 0
    death_cross = prev_diff >= 0 and curr_diff < 0

    rsi_val = float(rsi.iloc[-1])
    macd_val = float(macd_line.iloc[-1])
    macd_signal_val = float(macd_signal_line.iloc[-1])
    price = float(close.iloc[-1])

    if volume is not None and not pd.isna(volume.iloc[-1]):
        vol_avg = float(volume.rolling(cfg.volume_avg_period).mean().iloc[-1])
        volume_confirmed = vol_avg > 0 and float(volume.iloc[-1]) >= vol_avg * cfg.volume_confirm_multiplier
    else:
        volume_confirmed = False

    action = "HOLD"
    confluence = 0

    if golden_cross:
        confirmations = [
            rsi_val < cfg.rsi_overbought,
            macd_val > macd_signal_val,
            volume_confirmed,
            bb_mid.iloc[-1] < price < bb_upper.iloc[-1],
        ]
        confluence = sum(confirmations)
        if confluence >= cfg.confluence_required:
            action = "BUY"
    elif death_cross:
        confirmations = [
            rsi_val > cfg.rsi_oversold,
            macd_val < macd_signal_val,
            volume_confirmed,
            bb_lower.iloc[-1] < price < bb_mid.iloc[-1],
        ]
        confluence = sum(confirmations)
        if confluence >= cfg.confluence_required:
            action = "SELL"

    return Signal(
        action=action,
        price=price,
        sma_fast=float(sma_fast.iloc[-1]),
        sma_slow=float(sma_slow.iloc[-1]),
        rsi=rsi_val,
        macd=macd_val,
        macd_signal=macd_signal_val,
        confluence=confluence,
        confluence_required=cfg.confluence_required,
    )
