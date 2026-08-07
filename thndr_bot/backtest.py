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


def backtest_ticker(df: pd.DataFrame, symbol: str, cfg: StrategyConfig | None = None) -> BacktestResult:
    """Walk the strategy forward bar-by-bar (no lookahead) and simulate long-only trades."""
    cfg = cfg or STRATEGY
    min_bars = max(cfg.sma_slow, cfg.macd_slow + cfg.macd_signal_period, cfg.bb_period, cfg.volume_avg_period) + 2

    trades: list[Trade] = []
    open_trade: Trade | None = None

    for i in range(min_bars - 1, len(df)):
        window = df.iloc[: i + 1]
        signal = compute_signal(window, cfg=cfg)
        if signal is None:
            continue

        date = df.index[i]
        price = float(df["Close"].iloc[i])

        if signal.action == "BUY" and open_trade is None:
            open_trade = Trade(entry_date=date, entry_price=price)
        elif signal.action == "SELL" and open_trade is not None:
            open_trade.exit_date = date
            open_trade.exit_price = price
            trades.append(open_trade)
            open_trade = None

    if open_trade is not None:
        trades.append(open_trade)

    first_close = float(df["Close"].iloc[min_bars - 1])
    last_close = float(df["Close"].iloc[-1])
    buy_and_hold_return_pct = (last_close - first_close) / first_close * 100

    return BacktestResult(symbol=symbol, trades=trades, buy_and_hold_return_pct=buy_and_hold_return_pct)
