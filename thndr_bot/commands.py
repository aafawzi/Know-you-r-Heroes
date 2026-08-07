from __future__ import annotations

import json
import logging

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WATCHLIST_PATH, load_watchlist
from .notifier import send_telegram_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_GET_UPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"
OFFSET_PATH = WATCHLIST_PATH.parent / ".telegram_offset.json"

HELP_TEXT = (
    "Portfolio commands:\n"
    "/update SYMBOL COST QTY - set your average cost and share count (also marks it held), "
    "e.g. /update TALM 21.50 60\n"
    "/sell SYMBOL - mark a position fully closed (clears cost basis and quantity)\n"
    "/portfolio - show your current held positions\n"
    "/help - show this message\n\n"
    "Adding a brand-new ticker isn't supported here - ask directly and it'll get added to the watchlist."
)


def _find_ticker(tickers: list[dict], symbol: str) -> dict | None:
    symbol = symbol.upper()
    for ticker in tickers:
        if ticker["symbol"].upper() == symbol:
            return ticker
    return None


def _handle_command(text: str, tickers: list[dict]) -> tuple[str | None, bool]:
    """Apply one command in-place to `tickers`. Returns (reply text or None, changed)."""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return None, False

    cmd = parts[0][1:].lower().split("@")[0]  # strip a possible /cmd@BotName suffix
    args = parts[1:]

    if cmd in ("help", "start"):
        return HELP_TEXT, False

    if cmd == "portfolio":
        held = [t for t in tickers if t.get("held")]
        if not held:
            return "No held positions.", False
        lines = []
        for t in held:
            cost_basis = t.get("cost_basis")
            quantity = t.get("quantity")
            if cost_basis is not None and quantity is not None:
                lines.append(f"{t['symbol']}: cost {cost_basis:g}, qty {quantity:g}")
            else:
                lines.append(f"{t['symbol']}: cost basis not set")
        return "Your portfolio:\n" + "\n".join(lines), False

    if cmd == "update":
        if len(args) != 3:
            return "Usage: /update SYMBOL COST QTY (e.g. /update TALM 21.50 60)", False
        symbol, cost_str, qty_str = args
        ticker = _find_ticker(tickers, symbol)
        if ticker is None:
            return (
                f"Unknown symbol {symbol.upper()} - it needs to already be in the watchlist. "
                "Ask to add it first if it's a new position.",
                False,
            )
        try:
            cost_basis = float(cost_str)
            quantity = float(qty_str)
        except ValueError:
            return "Cost and quantity must be numbers, e.g. /update TALM 21.50 60", False
        ticker["cost_basis"] = cost_basis
        ticker["quantity"] = quantity
        ticker["held"] = True
        return f"Updated {ticker['symbol']}: cost {cost_basis:g}, qty {quantity:g}.", True

    if cmd == "sell":
        if len(args) != 1:
            return "Usage: /sell SYMBOL (e.g. /sell TALM)", False
        ticker = _find_ticker(tickers, args[0])
        if ticker is None:
            return f"Unknown symbol {args[0].upper()}.", False
        ticker["held"] = False
        ticker["cost_basis"] = None
        ticker["quantity"] = None
        return f"Marked {ticker['symbol']} as sold (no longer held).", True

    return f"Unknown command /{cmd}. Send /help for the list.", False


def _load_offset() -> int:
    if OFFSET_PATH.exists():
        try:
            return int(json.loads(OFFSET_PATH.read_text()).get("last_update_id", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            return 0
    return 0


def _save_offset(update_id: int) -> None:
    OFFSET_PATH.write_text(json.dumps({"last_update_id": update_id}) + "\n")


def _save_watchlist(tickers: list[dict]) -> None:
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["tickers"] = tickers
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _fetch_updates(offset: int) -> list[dict]:
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not configured; skipping command poll.")
        return []
    url = TELEGRAM_GET_UPDATES_URL.format(token=TELEGRAM_BOT_TOKEN)
    try:
        resp = requests.get(url, params={"offset": offset + 1, "timeout": 0}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Telegram getUpdates failed: %s", exc)
        return []
    return resp.json().get("result", [])


def poll_and_apply() -> bool:
    """Poll Telegram for new commands from the configured chat, apply them to
    the watchlist, and reply to each. Returns True if the watchlist changed
    (the caller should commit/push config/watchlist.json in that case).

    Only messages from TELEGRAM_CHAT_ID are honored - anyone else who
    messages the bot is ignored, since a command here can rewrite your
    portfolio data.
    """
    offset = _load_offset()
    updates = _fetch_updates(offset)
    if not updates:
        return False

    tickers = load_watchlist()
    changed = False
    max_update_id = offset

    for update in updates:
        max_update_id = max(max_update_id, update["update_id"])
        message = update.get("message")
        if not message or "text" not in message:
            continue

        chat_id = str(message.get("chat", {}).get("id", ""))
        if not TELEGRAM_CHAT_ID or chat_id != str(TELEGRAM_CHAT_ID):
            logger.warning("Ignoring command from unrecognized chat_id %s", chat_id)
            continue

        reply, did_change = _handle_command(message["text"], tickers)
        if did_change:
            changed = True
        if reply:
            send_telegram_message(reply)

    _save_offset(max_update_id)

    if changed:
        _save_watchlist(tickers)
        logger.info("Watchlist updated via Telegram command.")

    return changed


if __name__ == "__main__":
    poll_and_apply()
