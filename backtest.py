import argparse

from thndr_bot.backtest import backtest_ticker
from thndr_bot.config import load_watchlist
from thndr_bot.data import fetch_history


def _fmt(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def main(period: str = "3y") -> None:
    watchlist = load_watchlist()
    rows = []

    for ticker in watchlist:
        symbol = ticker["symbol"]
        yahoo_symbol = ticker["yahoo_symbol"]

        df = fetch_history(yahoo_symbol, period=period)
        if df is None:
            print(f"{symbol}: no data, skipping")
            continue

        result = backtest_ticker(df, symbol)
        closed = result.closed_trades
        stops = sum(1 for t in closed if t.exit_reason == "stop_loss")
        targets = sum(1 for t in closed if t.exit_reason == "take_profit")
        signals = sum(1 for t in closed if t.exit_reason == "signal")
        rows.append(
            {
                "symbol": symbol,
                "trades": len(closed),
                "open": result.trades and result.trades[-1].is_open,
                "win_rate": result.win_rate_pct,
                "avg_return": result.avg_return_pct,
                "total_return": result.total_return_pct,
                "max_drawdown": result.max_drawdown_pct,
                "buy_hold": result.buy_and_hold_return_pct,
                "exits": f"{stops}sl/{targets}tp/{signals}sig",
            }
        )

    header = (
        f"{'Symbol':<8}{'Trades':>7}{'Open':>6}{'WinRate%':>10}{'AvgRet%':>10}"
        f"{'TotalRet%':>12}{'MaxDD%':>9}{'BuyHold%':>10}  {'Exits(sl/tp/sig)'}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['symbol']:<8}{r['trades']:>7}{'Y' if r['open'] else '':>6}"
            f"{_fmt(r['win_rate']):>10}{_fmt(r['avg_return']):>10}{_fmt(r['total_return']):>12}"
            f"{_fmt(r['max_drawdown']):>9}{_fmt(r['buy_hold']):>10}  {r['exits']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default="3y", help="yfinance history period, e.g. 1y, 2y, 3y, 5y")
    args = parser.parse_args()
    main(period=args.period)
