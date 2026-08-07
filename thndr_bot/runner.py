from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import STRATEGY, load_watchlist
from .data import fetch_history
from .notifier import send_telegram_message
from .regime import compute_regime
from .strategy import compute_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _format_alert_line(
    symbol: str,
    name: str,
    held: bool,
    signal,
    cost_basis: float | None = None,
    quantity: float | None = None,
) -> str:
    held_tag = " — you hold this" if held else ""
    line = f"*{signal.action}* {symbol} ({name}) @ {signal.price:.2f} | RSI={signal.rsi:.1f}{held_tag}"

    if held and cost_basis is not None:
        pnl_pct = (signal.price - cost_basis) / cost_basis * 100
        line += f"\n    Your position: cost {cost_basis:.2f} → now {signal.price:.2f} ({pnl_pct:+.1f}%)"
        if quantity is not None:
            pnl_abs = (signal.price - cost_basis) * quantity
            line += f", {pnl_abs:+.2f} EGP on {quantity:g} shares"

    if signal.action == "BUY" and signal.stop_loss is not None and signal.take_profit is not None:
        risk_per_share = signal.price - signal.stop_loss
        stop_pct = (signal.stop_loss - signal.price) / signal.price * 100
        target_pct = (signal.take_profit - signal.price) / signal.price * 100
        line += (
            f"\n    Stop-loss: {signal.stop_loss:.2f} ({stop_pct:.1f}%) | "
            f"Take-profit (reference only): {signal.take_profit:.2f} (+{target_pct:.1f}%)\n"
            f"    Risk ≤{STRATEGY.risk_per_trade_pct:g}% of portfolio: "
            f"shares = (portfolio value × {STRATEGY.risk_per_trade_pct:g}%) ÷ {risk_per_share:.2f}"
        )

    return line


def _market_regime_context() -> str:
    """EGX30 vs its own SMA - informational context only, doesn't gate any signal.

    See backtest.py --regime-filter for whether gating on this actually
    helps before treating it as more than a "here's the backdrop" note.
    """
    index_df = fetch_history(STRATEGY.regime_index_symbol, period=STRATEGY.regime_history_period)
    if index_df is None:
        return "unavailable"
    logger.info(
        "%s: fetched %d rows (need %d for the SMA), %s to %s",
        STRATEGY.regime_index_symbol,
        len(index_df),
        STRATEGY.regime_sma_period,
        index_df.index[0].date() if len(index_df) else "n/a",
        index_df.index[-1].date() if len(index_df) else "n/a",
    )
    regime = compute_regime(index_df, sma_period=STRATEGY.regime_sma_period)
    return regime or "not enough history yet"


def run() -> None:
    watchlist = load_watchlist()
    market_regime = _market_regime_context()
    logger.info("Market regime (EGX30 vs %d-day SMA): %s", STRATEGY.regime_sma_period, market_regime)
    actionable: list[tuple[bool, str]] = []  # (held, formatted line)

    for ticker in watchlist:
        symbol = ticker["symbol"]
        yahoo_symbol = ticker["yahoo_symbol"]
        name = ticker.get("name", symbol)
        held = ticker.get("held", False)
        cost_basis = ticker.get("cost_basis")
        quantity = ticker.get("quantity")

        df = fetch_history(yahoo_symbol, period=STRATEGY.history_period)
        if df is None:
            continue

        signal = compute_signal(df)
        if signal is None:
            logger.info("%s: not enough history yet, skipping", symbol)
            continue

        logger.info(
            "%s (%s)%s: %s | price=%.2f SMA%d=%.2f SMA%d=%.2f RSI%d=%.1f",
            symbol,
            name,
            " [held]" if held else "",
            signal.action,
            signal.price,
            STRATEGY.sma_fast,
            signal.sma_fast,
            STRATEGY.sma_slow,
            signal.sma_slow,
            STRATEGY.rsi_period,
            signal.rsi,
        )

        if signal.action in ("BUY", "SELL"):
            actionable.append((held, _format_alert_line(symbol, name, held, signal, cost_basis, quantity)))

    # Portfolio positions surface first - a SELL signal on something you
    # actually hold is more urgent than a BUY idea on something you don't.
    actionable.sort(key=lambda item: not item[0])
    actionable_lines = [line for _held, line in actionable]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if actionable_lines:
        message = (
            f"EGX Signal Bot — {timestamp}\n"
            f"Market: EGX30 {market_regime} (vs {STRATEGY.regime_sma_period}-day avg)\n\n"
            + "\n".join(actionable_lines)
            + "\n\n_Signal only — not financial advice. Review and place any trade yourself in Thndr._"
        )
        send_telegram_message(message)
    else:
        logger.info("No actionable signals this run (%s).", timestamp)


if __name__ == "__main__":
    run()
