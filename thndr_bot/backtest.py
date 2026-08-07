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


def split_history(df: pd.DataFrame, split_frac: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a price history into an earlier in-sample slice and a later out-of-sample slice.

    Used to check whether a backtest result holds up on data the strategy
    wasn't eyeballed against, rather than trusting a single full-period run.
    """
    if not 0 < split_frac < 1:
        raise ValueError("split_frac must be between 0 and 1 (exclusive)")
    split_idx = int(len(df) * split_frac)
    return df.iloc[:split_idx], df.iloc[split_idx:]


def pooled_stats(results: list[BacktestResult]) -> dict:
    """Pool closed trades across multiple tickers into one win rate / avg return.

    A simple average of per-ticker win rates weights a ticker with 1 trade
    the same as one with 8; pooling trades first gives a more honest overall
    picture of how the strategy performed across the whole watchlist.
    """
    all_closed = [t for r in results for t in r.closed_trades]
    if not all_closed:
        return {"trades": 0, "win_rate": None, "avg_return": None}
    wins = sum(1 for t in all_closed if t.return_pct > 0)
    return {
        "trades": len(all_closed),
        "win_rate": wins / len(all_closed) * 100,
        "avg_return": sum(t.return_pct for t in all_closed) / len(all_closed),
    }


def backtest_ticker(
    df: pd.DataFrame,
    symbol: str,
    cfg: StrategyConfig | None = None,
    use_stop_loss_exit: bool = False,
    use_take_profit_exit: bool = False,
    use_trailing_stop_exit: bool = False,
    regime: pd.Series | None = None,
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

    use_trailing_stop_exit=True is the answer to *why* the fixed stop failed:
    the stop sits cfg.atr_trail_multiplier ATRs below the highest high reached
    since entry and ratchets up as the position runs, never down. A winner in
    a healthy uptrend drags its stop along behind it instead of waiting at the
    entry-time level to be clipped by the first ordinary pullback. Also opt-in
    and unproven - run the backtest before trusting it.

    `regime`, if given, must be a Series aligned to df's index (same length
    and order, e.g. via thndr_bot.regime.regime_series().reindex(df.index,
    method="ffill")) with values "bullish"/"bearish"/None. When present, a
    BUY signal is only taken while the regime is "bullish" - this is opt-in
    for comparison, not the live bot's default behavior. A None value for a
    given bar (regime undeterminable, e.g. not enough index history) does
    NOT block the BUY - only an explicit "bearish" does. Treating "unknown"
    the same as "bearish" would silently veto every trade whenever the index
    data is thin, which is exactly what happens with ^CASE30 today - see
    README.
    """
    cfg = cfg or STRATEGY
    min_bars = cfg.sma_slow + 2
    has_hl = "High" in df.columns and "Low" in df.columns

    trades: list[Trade] = []
    open_trade: Trade | None = None
    open_stop: float | None = None
    open_target: float | None = None
    open_trail: float | None = None
    open_peak: float | None = None

    for i in range(min_bars - 1, len(df)):
        date = df.index[i]
        price = float(df["Close"].iloc[i])

        if open_trade is not None and has_hl:
            low = float(df["Low"].iloc[i])
            high = float(df["High"].iloc[i])
            # Every level checked here was established on an earlier bar, so
            # acting on it now doesn't peek at data the strategy couldn't have
            # had. The trail for this bar is updated further down, after the
            # exit checks.
            if use_stop_loss_exit and open_stop is not None and low <= open_stop:
                open_trade.exit_date = date
                open_trade.exit_price = open_stop
                open_trade.exit_reason = "stop_loss"
                trades.append(open_trade)
                open_trade = open_stop = open_target = open_trail = open_peak = None
                continue
            if use_trailing_stop_exit and open_trail is not None and low <= open_trail:
                open_trade.exit_date = date
                open_trade.exit_price = open_trail
                open_trade.exit_reason = "trailing_stop"
                trades.append(open_trade)
                open_trade = open_stop = open_target = open_trail = open_peak = None
                continue
            if use_take_profit_exit and open_target is not None and high >= open_target:
                open_trade.exit_date = date
                open_trade.exit_price = open_target
                open_trade.exit_reason = "take_profit"
                trades.append(open_trade)
                open_trade = open_stop = open_target = open_trail = open_peak = None
                continue

        window = df.iloc[: i + 1]
        signal = compute_signal(window, cfg=cfg)
        if signal is None:
            continue

        if signal.action == "BUY" and open_trade is None:
            bar_regime = regime.iloc[i] if regime is not None else None
            if bar_regime is not None and bar_regime != "bullish":
                continue
            open_trade = Trade(entry_date=date, entry_price=price)
            open_stop = signal.stop_loss
            open_target = signal.take_profit
            open_peak = float(df["High"].iloc[i]) if has_hl else price
        elif signal.action == "SELL" and open_trade is not None:
            open_trade.exit_date = date
            open_trade.exit_price = price
            open_trade.exit_reason = "signal"
            trades.append(open_trade)
            open_trade = open_stop = open_target = open_trail = open_peak = None

        # Ratchet the trail up for the *next* bar: track the highest high seen
        # since entry and sit atr_trail_multiplier ATRs beneath it. max() is
        # what makes it a trailing stop rather than a recalculated one - a
        # falling price or an expanding ATR must never loosen the stop.
        if use_trailing_stop_exit and open_trade is not None and has_hl and signal.atr is not None:
            open_peak = max(open_peak, float(df["High"].iloc[i]))
            candidate = open_peak - cfg.atr_trail_multiplier * signal.atr
            open_trail = candidate if open_trail is None else max(open_trail, candidate)

    if open_trade is not None:
        trades.append(open_trade)

    first_close = float(df["Close"].iloc[min_bars - 1])
    last_close = float(df["Close"].iloc[-1])
    buy_and_hold_return_pct = (last_close - first_close) / first_close * 100

    return BacktestResult(symbol=symbol, trades=trades, buy_and_hold_return_pct=buy_and_hold_return_pct)
