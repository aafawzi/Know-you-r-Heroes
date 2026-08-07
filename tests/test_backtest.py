import pandas as pd
import pytest

from thndr_bot.backtest import backtest_ticker
from thndr_bot.config import StrategyConfig

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


def test_backtest_closes_trade_on_round_trip():
    # golden cross at index 4 (buy @ 20), death cross at index 7 (sell @ 0)
    closes = [10, 10, 10, 10, 20, 20, 20, 0]
    df = pd.DataFrame({"Close": closes})

    result = backtest_ticker(df, "TEST", cfg=_CFG)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.entry_price == 20
    assert trade.exit_price == 0
    assert trade.return_pct == -100
    assert result.win_rate_pct == 0
    assert result.total_return_pct == -100


def test_backtest_leaves_unresolved_trade_open():
    closes = [10, 10, 10, 10, 20]
    df = pd.DataFrame({"Close": closes})

    result = backtest_ticker(df, "TEST", cfg=_CFG)

    assert len(result.trades) == 1
    assert result.trades[0].is_open
    assert result.closed_trades == []
    assert result.win_rate_pct is None


def test_backtest_no_signals_no_trades():
    df = pd.DataFrame({"Close": [10.0] * 10})

    result = backtest_ticker(df, "TEST", cfg=_CFG)

    assert result.trades == []
    assert result.win_rate_pct is None


def test_backtest_exits_at_stop_loss_intraday():
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
        volume_confirm_multiplier=1.0,
        confluence_required=1,
        atr_period=2,
        atr_stop_multiplier=2.0,
        atr_reward_multiplier=3.0,
    )
    # Golden cross + BUY at index 4 (price=20, ATR(2)=6.5 -> stop=7.0, target=39.5).
    # Index 5's Low crashes through the stop before any SELL crossover happens.
    closes = [10, 10, 10, 10, 20, 20]
    highs = [11, 11, 11, 11, 21, 25]
    lows = [9, 9, 9, 9, 19, 5]
    df = pd.DataFrame({"Close": closes, "High": highs, "Low": lows})

    result = backtest_ticker(df, "TEST", cfg=cfg)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.entry_price == 20
    assert trade.exit_price == pytest.approx(7.0)
    assert trade.exit_reason == "stop_loss"


_ATR_CFG = StrategyConfig(
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
    atr_period=2,
    atr_stop_multiplier=2.0,
    atr_reward_multiplier=3.0,
)


def test_backtest_take_profit_is_informational_by_default():
    # Same BUY setup as the stop-loss test (stop=7.0, target=39.5), but index
    # 5's High blows through the take-profit while staying clear of the stop.
    closes = [10, 10, 10, 10, 20, 20]
    highs = [11, 11, 11, 11, 21, 45]
    lows = [9, 9, 9, 9, 19, 15]
    df = pd.DataFrame({"Close": closes, "High": highs, "Low": lows})

    result = backtest_ticker(df, "TEST", cfg=_ATR_CFG)

    assert len(result.trades) == 1
    assert result.trades[0].is_open  # take-profit alone no longer force-closes it
    assert result.closed_trades == []


def test_backtest_take_profit_exit_when_opted_in():
    closes = [10, 10, 10, 10, 20, 20]
    highs = [11, 11, 11, 11, 21, 45]
    lows = [9, 9, 9, 9, 19, 15]
    df = pd.DataFrame({"Close": closes, "High": highs, "Low": lows})

    result = backtest_ticker(df, "TEST", cfg=_ATR_CFG, use_take_profit_exit=True)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_price == pytest.approx(39.5)
    assert trade.exit_reason == "take_profit"
