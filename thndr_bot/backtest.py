from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import STRATEGY, StrategyConfig
from .strategy import compute_signal


@dataclass
class Trade:
    entry_date: object
    entry_price: float
    exit_date: object | None = None
    exit_price: float | None = None
    exit_reason: str | None = None  # "stop_loss", "take_profit", or "signal"

    @property
    def is_open(self) -> bool:
        return self.exit_date is None

    @property
    def return_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry_price) / self.entry_price * 100


@dataclass
class BacktestResult:
    symbol: str
    trades: list[Trade]
    buy_and_hold_return_pct: float

    @property
    def closed_trades(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    @property
    def win_rate_pct(self) -> float | None:
        closed = self.closed_trades
        if not closed:
            return None
        wins = sum(1 for t in closed if t.return_pct > 0)
        return wins / len(closed) * 100

    @property
    def avg_return_pct(self) -> float | None:
        closed = self.closed_trades
        if not closed:
            return None
        return sum(t.return_pct for t in closed) / len(closed)

    @property
    def total_return_pct(self) -> float | None:
        closed = self.closed_trades
        if not closed:
            return None
        equity = 1.0
        for t in closed:
            equity *= 1 + t.return_pct / 100
        return (equity - 1) * 100

    @property
    def max_drawdown_pct(self) -> float | None:
        closed = self.closed_trades
        if not closed:
            return None
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for t in closed:
            equity *= 1 + t.return_pct / 100
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)
        return max_dd


def backtest_ticker(
    df: pd.DataFrame,
    symbol: str,
    cfg: StrategyConfig | None = None,
    use_stop_loss_exit: bool = False,
    use_take_profit_exit: bool = False,
) -> BacktestResult:
    """Walk the strategy forward bar-by-bar (no lookahead) and simulate long-only trades.

    By default this is the plain baseline: a position opened on a BUY only
    closes on the next SELL crossover. Backtesting showed that forcing exits
    at a fixed ATR stop-loss and/or take-profit consistently gave up more
    upside than it protected on 3 years of EGX data - a static stop doesn't
    move up as a position becomes profitable, so a long-held winner in a
    healthy uptrend gets stopped out on an ordinary pullback. Pass
    use_stop_loss_exit=True and/or use_take_profit_exit=True to restore that
    behavior for comparison; the ATR levels are still computed either way and
    available on the Trade/Signal for reference.
    """
    cfg = cfg or STRATEGY
    min_bars = cfg.sma_slow + 2
    has_hl = "High" in df.columns and "Low" in df.columns

    trades: list[Trade] = []
    open_trade: Trade | None = None
    open_stop: float | None = None
    open_target: float | None = None

    for i in range(min_bars - 1, len(df)):
        date = df.index[i]
        price = float(df["Close"].iloc[i])

        if open_trade is not None and has_hl:
            low = float(df["Low"].iloc[i])
            high = float(df["High"].iloc[i])
            if use_stop_loss_exit and open_stop is not None and low <= open_stop:
                open_trade.exit_date = date
                open_trade.exit_price = open_stop
                open_trade.exit_reason = "stop_loss"
                trades.append(open_trade)
                open_trade = open_stop = open_target = None
                continue
            if use_take_profit_exit and open_target is not None and high >= open_target:
                open_trade.exit_date = date
                open_trade.exit_price = open_target
                open_trade.exit_reason = "take_profit"
                trades.append(open_trade)
                open_trade = open_stop = open_target = None
                continue

        window = df.iloc[: i + 1]
        signal = compute_signal(window, cfg=cfg)
        if signal is None:
            continue

        if signal.action == "BUY" and open_trade is None:
            open_trade = Trade(entry_date=date, entry_price=price)
            open_stop = signal.stop_loss
            open_target = signal.take_profit
        elif signal.action == "SELL" and open_trade is not None:
            open_trade.exit_date = date
            open_trade.exit_price = price
            open_trade.exit_reason = "signal"
            trades.append(open_trade)
            open_trade = open_stop = open_target = None

    if open_trade is not None:
        trades.append(open_trade)

    first_close = float(df["Close"].iloc[min_bars - 1])
    last_close = float(df["Close"].iloc[-1])
    buy_and_hold_return_pct = (last_close - first_close) / first_close * 100

    return BacktestResult(symbol=symbol, trades=trades, buy_and_hold_return_pct=buy_and_hold_return_pct)
