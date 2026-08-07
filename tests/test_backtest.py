import pandas as pd

from thndr_bot.backtest import backtest_ticker
from thndr_bot.config import StrategyConfig

_CFG = StrategyConfig(sma_fast=2, sma_slow=3, rsi_period=3, rsi_overbought=101, rsi_oversold=-1)


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
