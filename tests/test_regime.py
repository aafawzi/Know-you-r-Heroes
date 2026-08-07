import pandas as pd

from thndr_bot.regime import compute_regime, regime_series


def test_compute_regime_bullish_when_above_sma():
    # SMA(3) of the last 3 closes is 10; the latest close (12) sits above it.
    df = pd.DataFrame({"Close": [10, 10, 10, 8, 10, 12]})

    assert compute_regime(df, sma_period=3) == "bullish"


def test_compute_regime_bearish_when_below_sma():
    df = pd.DataFrame({"Close": [10, 10, 10, 12, 10, 8]})

    assert compute_regime(df, sma_period=3) == "bearish"


def test_compute_regime_insufficient_data_returns_none():
    df = pd.DataFrame({"Close": [10, 10]})

    assert compute_regime(df, sma_period=3) is None


def test_regime_series_has_no_lookahead_and_labels_each_bar():
    # SMA(2): idx0 nan, idx1=10, idx2=11, idx3=13.5, idx4=15.5
    closes = [10, 10, 12, 15, 16]
    df = pd.DataFrame({"Close": closes})

    series = regime_series(df, sma_period=2)

    assert series.iloc[0] is None
    assert series.iloc[1] == "bearish"  # close 10 == sma 10 -> not > sma
    assert series.iloc[2] == "bullish"  # close 12 > sma 11
    assert series.iloc[3] == "bullish"  # close 15 > sma 13.5
    assert series.iloc[4] == "bullish"  # close 16 > sma 15.5
