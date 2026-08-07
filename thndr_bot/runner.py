from __future__ import annotations

import logging
from datetime import datetime, timezone

from .config import STRATEGY, load_watchlist
from .data import fetch_history
from .notifier import send_telegram_message
from .strategy import compute_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run() -> None:
    watchlist = load_watchlist()
    actionable: list[tuple[bool, str]] = []  # (held, formatted line)

    for ticker in watchlist:
        symbol = ticker["symbol"]
        yahoo_symbol = ticker["yahoo_symbol"]
        name = ticker.get("name", symbol)
        held = ticker.get("held", False)

        df = fetch_history(yahoo_symbol, period=STRATEGY.history_period)
        if df is None:
            continue

        signal = compute_signal(df)
        if signal is None:
            logger.info("%s: not enough history yet, skipping", symbol)
            continue

        logger.info(
            "%s (%s)%s: %s | price=%.2f SMA%d=%.2f SMA%d=%.2f RSI%d=%.1f MACD=%.3f/%.3f confluence=%d/%d",
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
            signal.macd,
            signal.macd_signal,
            signal.confluence,
            signal.confluence_required,
        )

        if signal.action in ("BUY", "SELL"):
            held_tag = " — you hold this" if held else ""
            actionable.append(
                (
                    held,
                    f"*{signal.action}* {symbol} ({name}) @ {signal.price:.2f} | "
                    f"RSI={signal.rsi:.1f} | confluence {signal.confluence}/{signal.confluence_required}{held_tag}",
                )
            )

    # Portfolio positions surface first - a SELL signal on something you
    # actually hold is more urgent than a BUY idea on something you don't.
    actionable.sort(key=lambda item: not item[0])
    actionable_lines = [line for _held, line in actionable]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if actionable_lines:
        message = (
            f"EGX Signal Bot — {timestamp}\n\n"
            + "\n".join(actionable_lines)
            + "\n\n_Signal only — not financial advice. Review and place any trade yourself in Thndr._"
        )
        send_telegram_message(message)
    else:
        logger.info("No actionable signals this run (%s).", timestamp)


if __name__ == "__main__":
    run()
