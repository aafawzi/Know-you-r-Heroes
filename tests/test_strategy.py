import pandas as pd

from thndr_bot.config import StrategyConfig
from thndr_bot.strategy import compute_signal

# RSI overbought/oversold pushed to the extremes, and confluence_required=1,
# so these tests isolate the SMA-crossover logic: RSI alone always confirms,
# without needing to control MACD/volume/Bollinger on tiny synthetic series.
_CFG = StrategyConfig(
    sma_fast=2,
    sma_slow=3,
    rsi_period=3,
    rsi_overbought=101,
    rsi_oversold=-1,
    macd_fast=1,
    macd_slow=2,
    macd_signal_period=1,
    bb_period=2,
    bb_std=2.0,
    volume_avg_period=2,
    volume_confirm_multiplier=1.0,
    confluence_required=1,
)


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


def test_high_confluence_requirement_blocks_weak_crossover():
    # Same golden cross as test_golden_cross_triggers_buy, but require all 4
    # confirmations and make volume confirmation impossible to satisfy -
    # crossover should stay HOLD instead of firing BUY.
    cfg = StrategyConfig(
        sma_fast=2,
        sma_slow=3,
        rsi_period=3,
        rsi_overbought=101,
        rsi_oversold=-1,
        macd_fast=1,
        macd_slow=2,
        macd_signal_period=1,
        bb_period=2,
        bb_std=2.0,
        volume_avg_period=2,
        volume_confirm_multiplier=1000.0,  # no real volume can ever satisfy this
        confluence_required=4,
    )
    closes = [10, 10, 10, 10, 20]
    df = pd.DataFrame({"Close": closes, "Volume": [100.0] * 5})

    signal = compute_signal(df, cfg=cfg)

    assert signal is not None
    assert signal.action == "HOLD"
    assert signal.confluence < signal.confluence_required
