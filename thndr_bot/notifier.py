from __future__ import annotations

import logging

import requests

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID); skipping send.\n%s", text)
        return False

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)
        return False

    if resp.status_code != 200:
        logger.error("Telegram send failed (%s): %s", resp.status_code, resp.text)
        return False

    return True
