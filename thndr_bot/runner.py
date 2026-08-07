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
    actionable_lines: list[str] = []

    for ticker in watchlist:
        symbol = ticker["symbol"]
        yahoo_symbol = ticker["yahoo_symbol"]
        name = ticker.get("name", symbol)

        df = fetch_history(yahoo_symbol, period=STRATEGY.history_period)
        if df is None:
            continue

        signal = compute_signal(df)
        if signal is None:
            logger.info("%s: not enough history yet, skipping", symbol)
            continue

        logger.info(
            "%s (%s): %s | price=%.2f SMA%d=%.2f SMA%d=%.2f RSI%d=%.1f",
            symbol,
            name,
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
            actionable_lines.append(
                f"*{signal.action}* {symbol} ({name}) @ {signal.price:.2f} | RSI={signal.rsi:.1f}"
            )

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
