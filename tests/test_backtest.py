import pandas as pd
import pytest

from thndr_bot.backtest import backtest_ticker, pooled_stats, split_history
from thndr_bot.config import StrategyConfig

_CFG = StrategyConfig(sma_fast=2, sma_slow=3, rsi_period=3, rsi_overbought=101, rsi_oversold=-1)

_ATR_CFG = StrategyConfig(
    sma_fast=2,
    sma_slow=3,
    rsi_period=3,
    rsi_overbought=101,
    rsi_oversold=-1,
    atr_period=2,
    atr_stop_multiplier=2.0,
    atr_reward_multiplier=3.0,
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
    assert trade.exit_reason == "signal"
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


# Same BUY setup for all the ATR-exit tests below: golden cross + BUY at
# index 4 (price=20, ATR(2)=6.5 -> stop=7.0, target=39.5).
_ATR_CLOSES = [10, 10, 10, 10, 20, 20]


def test_stop_and_target_are_informational_by_default():
    # Index 5's range blows through both the stop and the target - by
    # default (the plain baseline), neither forces an exit; the trade rides
    # toward the next SELL crossover instead.
    highs = [11, 11, 11, 11, 21, 45]
    lows = [9, 9, 9, 9, 19, 5]
    df = pd.DataFrame({"Close": _ATR_CLOSES, "High": highs, "Low": lows})

    result = backtest_ticker(df, "TEST", cfg=_ATR_CFG)

    assert len(result.trades) == 1
    assert result.trades[0].is_open
    assert result.closed_trades == []


def test_backtest_exits_at_stop_loss_when_opted_in():
    # Index 5's Low crashes through the stop before any SELL crossover happens.
    highs = [11, 11, 11, 11, 21, 25]
    lows = [9, 9, 9, 9, 19, 5]
    df = pd.DataFrame({"Close": _ATR_CLOSES, "High": highs, "Low": lows})

    result = backtest_ticker(df, "TEST", cfg=_ATR_CFG, use_stop_loss_exit=True)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.entry_price == 20
    assert trade.exit_price == pytest.approx(7.0)
    assert trade.exit_reason == "stop_loss"


def test_backtest_exits_at_take_profit_when_opted_in():
    highs = [11, 11, 11, 11, 21, 45]
    lows = [9, 9, 9, 9, 19, 15]
    df = pd.DataFrame({"Close": _ATR_CLOSES, "High": highs, "Low": lows})

    result = backtest_ticker(df, "TEST", cfg=_ATR_CFG, use_take_profit_exit=True)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_price == pytest.approx(39.5)
    assert trade.exit_reason == "take_profit"


_TRAIL_CFG = StrategyConfig(
    sma_fast=2,
    sma_slow=3,
    rsi_period=3,
    rsi_overbought=101,
    rsi_oversold=-1,
    atr_period=2,
    atr_trail_multiplier=1.0,
)

# Shared setup for the trailing-stop tests: BUY at index 4 (price 12), a run up
# to a high of 16.2 at index 6, a quieter pullback bar at index 7, then a slump
# to 11 at index 8 that death-crosses. The trail ratchets 10.90 -> 12.00 ->
# 14.00 -> 14.50 across those bars.
_TRAIL_CLOSES = [10, 10, 10, 10, 12, 14, 16, 15, 11]
_TRAIL_HIGHS = [10.2, 10.2, 10.2, 10.2, 12.2, 14.2, 16.2, 15.2, 15.2]
_TRAIL_LOWS = [9.8, 9.8, 9.8, 9.8, 11.8, 13.8, 15.8, 14.8, 10.8]


def _trail_df():
    return pd.DataFrame({"Close": _TRAIL_CLOSES, "High": _TRAIL_HIGHS, "Low": _TRAIL_LOWS})


def test_trailing_stop_off_by_default_rides_the_reversal_down():
    result = backtest_ticker(_trail_df(), "TEST", cfg=_TRAIL_CFG)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    # Baseline behaviour: hold until the death cross, handing back the entire
    # run-up and closing below the entry price.
    assert trade.exit_reason == "signal"
    assert trade.exit_price == 11
    assert trade.return_pct < 0


def test_trailing_stop_banks_the_run_up_instead_of_giving_it_back():
    result = backtest_ticker(_trail_df(), "TEST", cfg=_TRAIL_CFG, use_trailing_stop_exit=True)

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_reason == "trailing_stop"
    assert trade.entry_price == 12
    # Exits at the trail (14.50) rather than the crossover price (11) - the
    # exact failure a fixed entry-time stop couldn't fix.
    assert trade.exit_price == pytest.approx(14.5)
    assert trade.return_pct > 0


def test_trailing_stop_ratchets_rather_than_recomputing_each_bar():
    # Index 7's high (15.2) is below the index 6 peak (16.2) while ATR shrinks
    # to 1.7. Ratcheting off the peak holds the stop at 16.2 - 1.7 = 14.50; a
    # stop recomputed from the current bar's high would slip to 15.2 - 1.7 =
    # 13.50. The exit price on index 8 tells the two apart.
    result = backtest_ticker(_trail_df(), "TEST", cfg=_TRAIL_CFG, use_trailing_stop_exit=True)

    assert result.closed_trades[0].exit_price == pytest.approx(14.5)
    assert result.closed_trades[0].exit_price != pytest.approx(13.5)


def test_trailing_stop_leaves_the_sell_crossover_in_charge_when_never_breached():
    # A far-away trail (10 ATRs) is never touched, so the trade must still exit
    # on the death cross - the trailing stop only ever preempts that exit.
    far_cfg = StrategyConfig(
        sma_fast=2, sma_slow=3, rsi_period=3, rsi_overbought=101, rsi_oversold=-1,
        atr_period=2, atr_trail_multiplier=10.0,
    )

    result = backtest_ticker(_trail_df(), "TEST", cfg=far_cfg, use_trailing_stop_exit=True)

    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].exit_reason == "signal"
    assert result.closed_trades[0].exit_price == 11


def test_regime_filter_blocks_buy_in_bear_market():
    # Same golden cross as test_backtest_closes_trade_on_round_trip, but the
    # regime is "bearish" on the entry bar - no trade should open at all.
    closes = [10, 10, 10, 10, 20, 20, 20, 0]
    df = pd.DataFrame({"Close": closes})
    regime = pd.Series(["bearish"] * len(df), index=df.index)

    result = backtest_ticker(df, "TEST", cfg=_CFG, regime=regime)

    assert result.trades == []


def test_regime_filter_allows_buy_in_bull_market():
    closes = [10, 10, 10, 10, 20, 20, 20, 0]
    df = pd.DataFrame({"Close": closes})
    regime = pd.Series(["bullish"] * len(df), index=df.index)

    result = backtest_ticker(df, "TEST", cfg=_CFG, regime=regime)

    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].entry_price == 20


def test_regime_filter_allows_buy_when_regime_unknown():
    # A None per-bar regime (e.g. not enough index history, as currently
    # happens with ^CASE30) must not be treated the same as "bearish" -
    # that would silently veto every trade whenever index data is thin.
    closes = [10, 10, 10, 10, 20, 20, 20, 0]
    df = pd.DataFrame({"Close": closes})
    regime = pd.Series([None] * len(df), index=df.index)

    result = backtest_ticker(df, "TEST", cfg=_CFG, regime=regime)

    assert len(result.closed_trades) == 1
    assert result.closed_trades[0].entry_price == 20


def test_split_history_divides_by_fraction():
    df = pd.DataFrame({"Close": list(range(10))})

    in_sample, out_of_sample = split_history(df, split_frac=0.6)

    assert len(in_sample) == 6
    assert len(out_of_sample) == 4
    assert list(in_sample["Close"]) == [0, 1, 2, 3, 4, 5]
    assert list(out_of_sample["Close"]) == [6, 7, 8, 9]


def test_split_history_rejects_invalid_fraction():
    df = pd.DataFrame({"Close": [1.0, 2.0]})

    with pytest.raises(ValueError):
        split_history(df, split_frac=1.5)


def test_pooled_stats_combines_trades_across_tickers():
    df_a = pd.DataFrame({"Close": [10, 10, 10, 10, 20, 40, 40, 25]})  # buy@20, sell@25 -> +25%
    result_a = backtest_ticker(df_a, "A", cfg=_CFG)

    df_b = pd.DataFrame({"Close": [10, 10, 10, 10, 20, 60, 60, 45]})  # buy@20, sell@45 -> +125%
    result_b = backtest_ticker(df_b, "B", cfg=_CFG)

    stats = pooled_stats([result_a, result_b])

    assert stats["trades"] == 2
    assert stats["win_rate"] == 100.0
    assert stats["avg_return"] == pytest.approx((25 + 125) / 2)


def test_pooled_stats_empty_when_no_closed_trades():
    df = pd.DataFrame({"Close": [10.0] * 10})
    result = backtest_ticker(df, "TEST", cfg=_CFG)

    stats = pooled_stats([result])

    assert stats == {"trades": 0, "win_rate": None, "avg_return": None}
