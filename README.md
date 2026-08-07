# EGX Signal Bot

A **signal-only** trading assistant for EGX (Egyptian Exchange) stocks. It does **not**
place trades and does **not** connect to your Thndr account in any way — it fetches
public market data, computes a simple technical signal, and sends you a Telegram
alert. You decide whether to act on it, and place any trade yourself in the Thndr app.

## Why signal-only?

Thndr does not publish a public API for algorithmic trading. Automating order
placement would mean driving Thndr's private mobile-app API or its UI directly,
which is undocumented, likely against Thndr's Terms of Service, and risks getting
your account flagged or banned. This project intentionally stays on the safe side
of that line: it only reads public market data and never touches your brokerage
account or credentials.

**Not financial advice.** This is a basic technical-indicator bot for personal use.
Verify signals yourself before acting on them.

## How it works

1. For each ticker in `config/watchlist.json`, fetch daily OHLC price history from
   Yahoo Finance (EGX tickers use the `.CA` suffix, e.g. `COMI.CA`).
2. Compute a 20-day and 50-day SMA (simple moving average) and a 14-day RSI.
3. Signal logic:
   - **BUY** when the 20-day SMA crosses above the 50-day SMA ("golden cross") and
     RSI is below 70 (not already overbought).
   - **SELL** when the 20-day SMA crosses below the 50-day SMA ("death cross") and
     RSI is above 30 (not already oversold).
   - Otherwise: **HOLD** (no alert sent).
4. Any BUY/SELL signals are sent to you as a single Telegram message.

These parameters live in `thndr_bot/config.py` (`StrategyConfig`) if you want to tune
them.

## About the watchlist — read before using

`config/watchlist.json` ships with a **starter list** of EGX tickers picked by
excluding obviously non-compliant sectors (conventional banks, insurers,
interest-based finance/brokerages, alcohol, tobacco, gambling). **This is not a
certified Sharia screening** — it wasn't cross-checked against the official EGX
Shariah Index or a qualified Sharia advisory board, and index composition changes
over time. Verify each ticker yourself (e.g. against EGX's published Shariah Index
constituents or a screening service) before relying on it, and edit the JSON file
to match your own list. Add/remove tickers as `{ "symbol": "XXXX", "yahoo_symbol":
"XXXX.CA", "name": "Company Name" }`.

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes runtime deps + pytest
```

### 2. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, and
   follow the prompts. You'll get a **bot token**.
2. Start a chat with your new bot (send it any message) so it's allowed to message
   you back.
3. Get your **chat ID**: message [@userinfobot](https://t.me/userinfobot) (or call
   `https://api.telegram.org/bot<token>/getUpdates` after messaging your bot) to
   find it.

### 3. Configure secrets

Copy `.env.example` to `.env` and fill in the values for local runs:

```bash
cp .env.example .env
```

```
TELEGRAM_BOT_TOKEN=123456:ABC-your-token
TELEGRAM_CHAT_ID=123456789
```

If these are left blank, the bot still runs and logs signals to the console/log —
it just skips sending Telegram messages.

### 4. Run it locally

```bash
python run.py
```

### 5. Run tests

```bash
pytest
```

## Scheduling (GitHub Actions)

`.github/workflows/egx-signals.yml` runs the bot automatically on a cron schedule
(default: ~15:30 Cairo time, Sunday–Thursday, after the EGX close) and can also be
triggered manually from the Actions tab.

To enable it:

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**.
2. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Push this repo to GitHub — the workflow runs on the schedule automatically.

Adjust the cron expression if Egypt's UTC offset changes (DST) or you want a
different check-in time.

## Project layout

```
run.py                          entry point
thndr_bot/
  config.py                     env vars, strategy parameters, watchlist loader
  data.py                       Yahoo Finance price fetching
  strategy.py                   SMA-crossover + RSI signal logic
  notifier.py                   Telegram sending
  runner.py                     orchestrates fetch -> signal -> notify for the watchlist
config/watchlist.json           tickers to track (edit this to change coverage)
tests/test_strategy.py          unit tests for the signal logic
.github/workflows/egx-signals.yml   scheduled run via GitHub Actions
```
