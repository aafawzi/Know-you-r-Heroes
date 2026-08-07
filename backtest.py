import argparse

import pandas as pd

from thndr_bot.backtest import backtest_ticker, pooled_stats, split_history
from thndr_bot.config import STRATEGY, load_watchlist
from thndr_bot.data import fetch_history
from thndr_bot.regime import regime_series


def _fmt(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def _row_for(symbol: str, result) -> dict:
    closed = result.closed_trades
    stops = sum(1 for t in closed if t.exit_reason == "stop_loss")
    trails = sum(1 for t in closed if t.exit_reason == "trailing_stop")
    targets = sum(1 for t in closed if t.exit_reason == "take_profit")
    signals = sum(1 for t in closed if t.exit_reason == "signal")
    return {
        "symbol": symbol,
        "trades": len(closed),
        "open": result.trades and result.trades[-1].is_open,
        "win_rate": result.win_rate_pct,
        "avg_return": result.avg_return_pct,
        "total_return": result.total_return_pct,
        "max_drawdown": result.max_drawdown_pct,
        "buy_hold": result.buy_and_hold_return_pct,
        "exits": f"{stops}sl/{trails}tr/{targets}tp/{signals}sig",
    }


def _print_table(rows: list[dict], label: str | None = None) -> None:
    if label:
        print(f"\n== {label} ==")
    header = (
        f"{'Symbol':<8}{'Trades':>7}{'Open':>6}{'WinRate%':>10}{'AvgRet%':>10}"
        f"{'TotalRet%':>12}{'MaxDD%':>9}{'BuyHold%':>10}  {'Exits(sl/tr/tp/sig)'}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['symbol']:<8}{r['trades']:>7}{'Y' if r['open'] else '':>6}"
            f"{_fmt(r['win_rate']):>10}{_fmt(r['avg_return']):>10}{_fmt(r['total_return']):>12}"
            f"{_fmt(r['max_drawdown']):>9}{_fmt(r['buy_hold']):>10}  {r['exits']}"
        )


def _print_pooled(results: list, label: str) -> None:
    stats = pooled_stats(results)
    print(
        f"\nPooled {label}: {stats['trades']} closed trades across watchlist | "
        f"win rate {_fmt(stats['win_rate'])}% | avg return/trade {_fmt(stats['avg_return'])}%"
    )


def _aligned_regime(full_regime: pd.Series | None, df: pd.DataFrame) -> pd.Series | None:
    if full_regime is None:
        return None
    return full_regime.reindex(df.index, method="ffill")


def main(
    period: str = "3y",
    split_frac: float | None = None,
    use_regime_filter: bool = False,
    use_trailing_stop: bool = False,
) -> None:
    watchlist = load_watchlist()

    full_regime = None
    if use_regime_filter:
        index_df = fetch_history(STRATEGY.regime_index_symbol, period=period)
        if index_df is None:
            print(f"Could not fetch {STRATEGY.regime_index_symbol} for the regime filter - continuing without it.")
        else:
            full_regime = regime_series(index_df, sma_period=STRATEGY.regime_sma_period)

    if split_frac is None:
        rows = []
        results = []
        for ticker in watchlist:
            symbol, yahoo_symbol = ticker["symbol"], ticker["yahoo_symbol"]
            df = fetch_history(yahoo_symbol, period=period)
            if df is None:
                print(f"{symbol}: no data, skipping")
                continue
            result = backtest_ticker(
                df,
                symbol,
                use_trailing_stop_exit=use_trailing_stop,
                regime=_aligned_regime(full_regime, df),
            )
            results.append(result)
            rows.append(_row_for(symbol, result))
        _print_table(rows)
        _print_pooled(results, f"({period})")
        return

    in_rows, out_rows = [], []
    in_results, out_results = [], []
    for ticker in watchlist:
        symbol, yahoo_symbol = ticker["symbol"], ticker["yahoo_symbol"]
        df = fetch_history(yahoo_symbol, period=period)
        if df is None:
            print(f"{symbol}: no data, skipping")
            continue

        in_df, out_df = split_history(df, split_frac)

        in_result = backtest_ticker(
            in_df,
            symbol,
            use_trailing_stop_exit=use_trailing_stop,
            regime=_aligned_regime(full_regime, in_df),
        )
        in_results.append(in_result)
        in_rows.append(_row_for(symbol, in_result))

        out_result = backtest_ticker(
            out_df,
            symbol,
            use_trailing_stop_exit=use_trailing_stop,
            regime=_aligned_regime(full_regime, out_df),
        )
        out_results.append(out_result)
        out_rows.append(_row_for(symbol, out_result))

    _print_table(in_rows, label=f"IN-SAMPLE (first {split_frac:.0%} of {period})")
    _print_pooled(in_results, "in-sample")
    _print_table(out_rows, label=f"OUT-OF-SAMPLE (last {1 - split_frac:.0%} of {period})")
    _print_pooled(out_results, "out-of-sample")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="3y", help="yfinance history period, e.g. 1y, 2y, 3y, 5y")
    parser.add_argument(
        "--split",
        type=float,
        default=None,
        metavar="FRACTION",
        help="e.g. 0.6 to backtest the first 60%% of the period (in-sample) and last 40%% (out-of-sample) separately",
    )
    parser.add_argument(
        "--regime-filter",
        action="store_true",
        help="Only take BUY signals while EGX30 is above its own SMA, for comparison against the unfiltered baseline",
    )
    parser.add_argument(
        "--trailing-stop",
        action="store_true",
        help="Exit at an ATR trailing stop that ratchets up behind the highest high since entry",
    )
    args = parser.parse_args()
    main(
        period=args.period,
        split_frac=args.split,
        use_regime_filter=args.regime_filter,
        use_trailing_stop=args.trailing_stop,
    )
