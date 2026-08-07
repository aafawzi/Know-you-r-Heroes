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

    # ATR-based risk-management levels shown alongside BUY alerts as a
    # reference only - backtesting showed forcing exits at these levels
    # (via confluence filters, forced stop-loss, or forced take-profit)
    # consistently underperformed the plain crossover strategy on 3 years of
    # EGX data, so nothing here gates or auto-exits a signal.
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    atr_reward_multiplier: float = 3.0
    risk_per_trade_pct: float = 1.0

    # Trailing-stop distance, in ATRs below the highest high reached since
    # entry. Unlike atr_stop_multiplier (a fixed level set at entry), this
    # ratchets up as a position runs and never moves down - the specific
    # weakness that made the fixed stop underperform. Opt-in for backtest
    # comparison; see backtest.py --trailing-stop.
    atr_trail_multiplier: float = 3.0

    # EGX30 market-regime context shown in alerts (bullish/bearish vs. the
    # index's own SMA). Informational only by default - see
    # backtest.py --regime-filter for whether gating BUY signals on it
    # actually helps before relying on it as more than context.
    regime_index_symbol: str = "^CASE30"
    regime_sma_period: int = 200
    regime_history_period: str = "2y"


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

STRATEGY = StrategyConfig()


def load_watchlist() -> list[dict]:
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["tickers"]
