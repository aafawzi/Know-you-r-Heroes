import pandas as pd

from thndr_bot.config import StrategyConfig
from thndr_bot.strategy import compute_signal

# RSI overbought/oversold pushed to the extremes so these tests isolate the
# SMA-crossover logic without tripping on RSI's own edge cases (RSI hits
# exactly 0 or 100 on short, one-directional synthetic series).
_CFG = StrategyConfig(sma_fast=2, sma_slow=3, rsi_period=3, rsi_overbought=101, rsi_oversold=-1)


def test_golden_cross_triggers_buy():
    closes = [10, 10, 10, 10, 20]
    df = pd.DataFrame({"Close": closes})

    signal = compute_signal(df, cfg=_CFG)

    assert signal is not None
    assert signal.action == "BUY"


def test_death_cross_triggers_sell():
    closes = [10, 10, 10, 10, 0]
    df = pd.DataFrame({"Close": closes})

    signal = compute_signal(df, cfg=_CFG)

    assert signal is not None
    assert signal.action == "SELL"


def test_no_crossover_holds():
    # Fast SMA is already above slow SMA on both the prior and current bar (no cross).
    closes = [10, 11, 12, 13, 14]
    df = pd.DataFrame({"Close": closes})

    signal = compute_signal(df, cfg=_CFG)

    assert signal is not None
    assert signal.action == "HOLD"


def test_insufficient_data_returns_none():
    df = pd.DataFrame({"Close": [100.0] * 10})

    assert compute_signal(df, cfg=_CFG) is None
