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
2. Compute a 20-day/50-day SMA crossover, 14-day RSI, MACD(12,26,9), Bollinger
   Bands(20, 2σ), and volume vs its 20-day average.
3. Signal logic — a crossover alone is *not* enough to fire:
   - A **golden cross** (20-day SMA crosses above 50-day) is a candidate BUY.
   - A **death cross** (20-day SMA crosses below 50-day) is a candidate SELL.
   - The candidate only fires if at least `confluence_required` (default 2) of these
     four also agree: RSI not overbought/oversold, MACD aligned with the direction,
     volume above its 20-day average, price positioned on the right side of the
     Bollinger mid-band. This exists to cut down whipsaws — see the backtest section
     below for what this tradeoff actually looks like on real data.
   - Otherwise: **HOLD** (no alert sent).
4. A BUY signal also computes an ATR(14)-based stop-loss (entry − 2×ATR) and
   take-profit (entry + 3×ATR), included in the alert along with a position-sizing
   formula (risk ≤1% of portfolio per trade — you supply your own portfolio value).
5. Any BUY/SELL signals are sent to you as a single Telegram message, held positions
   first.

These parameters (SMA windows, RSI/MACD/Bollinger/volume settings, confluence
threshold, ATR multipliers, risk-per-trade %) all live in `thndr_bot/config.py`
(`StrategyConfig`) if you want to tune them.

## Backtesting — know what you're getting into first

Before trusting any of this, run the backtest: `python backtest.py --period 3y` (or
trigger the **Backtest** workflow from the Actions tab, since Yahoo Finance isn't
reachable from every environment). It walks the strategy forward bar-by-bar (no
lookahead) against real historical data and reports win rate, average/total return,
max drawdown, and a buy-and-hold comparison per ticker, plus a breakdown of how each
closed trade exited (stop-loss / take-profit / signal).

The honest finding from the last full run: **EGX has been in a strong multi-year
uptrend, and simple buy-and-hold beat this strategy on most tickers, often by a
lot.** Trend-following signal strategies structurally give up some upside in
strongly trending markets in exchange for cutting losses when a name actually
reverses (see `MFPC` in a backtest run — buy-and-hold lost ~93%, the strategy only
lost ~20%). Whether that tradeoff is worth it for a given ticker is genuinely mixed,
not a clean win — look at the actual backtest output before assuming the bot's
signals are reliable.

## About the watchlist — read before using

`config/watchlist.json` ships with a **starter list** of EGX tickers picked by
excluding obviously non-compliant sectors (conventional banks, insurers,
interest-based finance/brokerages, alcohol, tobacco, gambling). **This is not a
certified Sharia screening** — it wasn't cross-checked against the official EGX
Shariah Index or a qualified Sharia advisory board, and index composition changes
over time. Verify each ticker yourself (e.g. against EGX's published Shariah Index
constituents or a screening service) before relying on it, and edit the JSON file
to match your own list. Add/remove tickers as `{ "symbol": "XXXX", "yahoo_symbol":
"XXXX.CA", "name": "Company Name", "held": false }`.

### Marking your actual Thndr holdings

Set `"held": true` on any ticker you actually own in Thndr. The bot doesn't connect
to your Thndr account (see above for why), so it has no way to know your real
positions — this field is how you tell it manually. Held positions get tagged
"— you hold this" in alerts and are sorted to the top of the message, since a SELL
signal on something you own is more time-sensitive than a BUY idea on something you
don't. Add any tickers you hold that aren't already in the starter list, with
`held: true`.

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

`.github/workflows/egx-signal-bot.yml` runs the bot automatically on a cron schedule
(default: ~15:30 Cairo time, Sunday–Thursday, after the EGX close) and can also be
triggered manually from the Actions tab ("Run workflow"). A separate
`.github/workflows/backtest.yml` workflow runs `backtest.py` on demand (accepts a
`period` input, e.g. `1y`/`3y`/`5y`) for when you want fresh numbers without pulling
the repo locally.

To enable the scheduled bot:

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**.
2. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Push this repo to GitHub — the workflow runs on the schedule automatically.

Adjust the cron expression if Egypt's UTC offset changes (DST) or you want a
different check-in time.

> Note: on a brand new repo, GitHub sometimes won't register a workflow (or allow
> manual dispatch) until it has fired at least once via a trigger that already
> works, e.g. a `push`. If `workflow_dispatch` 404s on a workflow you just added,
> temporarily add a `push` trigger scoped to that workflow file, push once, then
> remove it.

## Project layout

```
run.py                          entry point for the live signal bot
backtest.py                     entry point for the backtest report
thndr_bot/
  config.py                     env vars, strategy parameters, watchlist loader
  data.py                       Yahoo Finance price fetching
  strategy.py                   SMA-crossover + confluence (RSI/MACD/BB/volume) +
                                 ATR stop-loss/take-profit signal logic
  backtest.py                   walk-forward trade simulator + performance metrics
  notifier.py                   Telegram sending
  runner.py                     orchestrates fetch -> signal -> notify for the watchlist
config/watchlist.json           tickers to track (edit this to change coverage)
tests/                          unit tests for signal logic and the backtest simulator
.github/workflows/egx-signal-bot.yml   scheduled live run via GitHub Actions
.github/workflows/backtest.yml         on-demand backtest run via GitHub Actions
```
