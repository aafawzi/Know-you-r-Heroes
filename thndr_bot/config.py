from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT_DIR / "config" / "watchlist.json"


@dataclass(frozen=True)
class StrategyConfig:
    sma_fast: int = 20
    sma_slow: int = 50
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    history_period: str = "1y"

    # Confluence filters layered on top of the SMA crossover to cut down on
    # whipsaws: a crossover only fires a signal once at least
    # `confluence_required` of {RSI, MACD, volume, Bollinger position} agree.
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal_period: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    volume_avg_period: int = 20
    volume_confirm_multiplier: float = 1.2
    confluence_required: int = 2


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STRATEGY = StrategyConfig()


def load_watchlist() -> list[dict]:
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["tickers"]
