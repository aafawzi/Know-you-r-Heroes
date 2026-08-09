from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import STRATEGY, load_watchlist
from .data import fetch_history
from .notifier import send_telegram_message
from .providers import Quality, fetch_index
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


def _portfolio_line(
    symbol: str,
    name: str,
    price: float,
    cost_basis: float | None,
    quantity: float | None,
) -> tuple[str, float | None]:
    """One line for the always-sent portfolio summary. Returns (line, pnl_abs)."""
    line = f"{symbol} ({name}): {price:.2f} EGP"
    pnl_abs = None
    if cost_basis is not None:
        pnl_pct = (price - cost_basis) / cost_basis * 100
        line += f" | cost {cost_basis:.2f} → {pnl_pct:+.1f}%"
        if quantity is not None:
            pnl_abs = (price - cost_basis) * quantity
            line += f", {pnl_abs:+.2f} EGP on {quantity:g} shares"
    else:
        line += " | cost basis not set"
    return line, pnl_abs


def _market_regime_context() -> str:
    """EGX30 vs its own SMA - informational context only, doesn't gate any signal.

    See backtest.py --regime-filter for whether gating on this actually
    helps before treating it as more than a "here's the backdrop" note.
    """
    result = fetch_index(
        STRATEGY.regime_index_symbol,
        period_days=STRATEGY.regime_history_days,
    )
    if not result.usable:
        return f"unavailable ({result.quality.value.lower()})"

    logger.info(
        "%s: %d rows [%s], %s to %s",
        STRATEGY.regime_index_symbol,
        len(result.frame),
        result.quality.value,
        result.frame.index[0].date(),
        result.frame.index[-1].date(),
    )

    regime = compute_regime(result.frame, sma_period=STRATEGY.regime_sma_period)
    if regime is None:
        return "not enough history yet"

    # Say so when the number is from cache rather than a live pull - a
    # regime read is only as current as the data behind it.
    return f"{regime} (stale data)" if result.quality is Quality.STALE else regime


def run() -> None:
    watchlist = load_watchlist()
    market_regime = _market_regime_context()
    logger.info("Market regime (EGX30 vs %d-day SMA): %s", STRATEGY.regime_sma_period, market_regime)
    actionable: list[tuple[bool, str]] = []  # (held, formatted line)
    portfolio_lines: list[str] = []
    total_pnl = 0.0
    any_pnl_known = False
    any_cost_basis_missing = False

    for ticker in watchlist:
        symbol = ticker["symbol"]
        yahoo_symbol = ticker["yahoo_symbol"]
        name = ticker.get("name", symbol)
        held = ticker.get("held", False)
        cost_basis = ticker.get("cost_basis")
        quantity = ticker.get("quantity")

        df = fetch_history(yahoo_symbol, period=STRATEGY.history_period)
        if df is None:
            if held:
                portfolio_lines.append(f"{symbol} ({name}): price unavailable")
            continue

        signal = compute_signal(df)
        if signal is None:
            logger.info("%s: not enough history yet, skipping", symbol)
            if held:
                portfolio_lines.append(f"{symbol} ({name}): not enough history yet")
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

        if held:
            line, pnl_abs = _portfolio_line(symbol, name, signal.price, cost_basis, quantity)
            portfolio_lines.append(line)
            if pnl_abs is not None:
                total_pnl += pnl_abs
                any_pnl_known = True
            else:
                any_cost_basis_missing = True

        if signal.action in ("BUY", "SELL"):
            actionable.append((held, _format_alert_line(symbol, name, held, signal, cost_basis, quantity)))

    # Portfolio positions surface first - a SELL signal on something you
    # actually hold is more urgent than a BUY idea on something you don't.
    actionable.sort(key=lambda item: not item[0])
    actionable_lines = [line for _held, line in actionable]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not portfolio_lines and not actionable_lines:
        logger.info("No held positions and no actionable signals this run (%s).", timestamp)
        return

    sections = [
        f"EGX Signal Bot — {timestamp}",
        f"Market: EGX30 {market_regime} (vs {STRATEGY.regime_sma_period}-day avg)",
    ]

    if portfolio_lines:
        portfolio_block = "📊 Your Portfolio\n" + "\n".join(portfolio_lines)
        if any_pnl_known:
            note = " (partial — some positions missing cost basis)" if any_cost_basis_missing else ""
            portfolio_block += f"\nTotal unrealized P&L: {total_pnl:+.2f} EGP{note}"
        sections.append(portfolio_block)

    if actionable_lines:
        sections.append("🔔 Signals\n" + "\n".join(actionable_lines))

    message = (
        "\n\n".join(sections)
        + "\n\n_Signal only — not financial advice. Review and place any trade yourself in Thndr._"
    )
    send_telegram_message(message)


if __name__ == "__main__":
    run()
