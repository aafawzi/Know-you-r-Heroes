import pandas as pd
import pytest

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


def test_rsi_overbought_blocks_buy():
    cfg = StrategyConfig(sma_fast=2, sma_slow=3, rsi_period=3, rsi_overbought=50, rsi_oversold=-1)
    closes = [10, 10, 10, 10, 20]  # same golden cross, but RSI will be well above 50
    df = pd.DataFrame({"Close": closes})

    signal = compute_signal(df, cfg=cfg)

    assert signal is not None
    assert signal.action == "HOLD"


def test_buy_signal_includes_atr_stop_and_take_profit_reference():
    cfg = StrategyConfig(
        sma_fast=2,
        sma_slow=3,
        rsi_period=3,
        rsi_overbought=101,
        rsi_oversold=-1,
        atr_period=2,
        atr_stop_multiplier=2.0,
        atr_reward_multiplier=3.0,
    )
    closes = [10, 10, 10, 10, 20]
    df = pd.DataFrame(
        {
            "Close": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
        }
    )

    signal = compute_signal(df, cfg=cfg)

    assert signal is not None
    assert signal.action == "BUY"
    # TR sequence is [nan, 2, 2, 2, 11] -> ATR(2) at the last bar = mean(2, 11) = 6.5
    assert signal.atr == pytest.approx(6.5)
    assert signal.stop_loss == pytest.approx(20 - 2.0 * 6.5)
    assert signal.take_profit == pytest.approx(20 + 3.0 * 6.5)


def test_sell_signal_has_no_stop_loss_or_take_profit():
    closes = [10, 10, 10, 10, 0]
    df = pd.DataFrame(
        {
            "Close": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
        }
    )

    signal = compute_signal(df, cfg=_CFG)

    assert signal is not None
    assert signal.action == "SELL"
    assert signal.stop_loss is None
    assert signal.take_profit is None
