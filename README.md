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
4. A BUY signal also computes an ATR(14)-based stop-loss (entry − 2×ATR) and
   take-profit (entry + 3×ATR), shown in the alert as **reference only** along with
   a position-sizing formula (risk ≤1% of portfolio per trade — you supply your own
   portfolio value). Nothing in the bot forces an exit at these levels; that's a
   deliberate, backtest-informed choice — see below.
5. Every run also fetches the EGX30 index (`^CASE30`) and computes whether it's
   above or below its own 200-day SMA - shown at the top of the Telegram message as
   market context (e.g. "Market: EGX30 bullish (vs 200-day avg)"). Like the ATR
   levels, this is **informational only** and doesn't gate any signal; see
   `backtest.py --regime-filter` below for whether gating on it would actually help.
   **Known limitation:** as of writing, Yahoo Finance only serves `^CASE30` a
   1-day/5-day history range no matter what period is requested (confirmed by
   probing `2y`/`5y`/`max` directly, and true of the `^EGX30.CA` and
   `^EGX30CAPPED.CA` alternates too) - nowhere near the 200 days needed for the
   SMA. Until Yahoo backfills deeper index history, live runs will show "Market:
   EGX30 unavailable (Yahoo Finance isn't serving deep history for ^CASE30 right
   now)" instead of a real bullish/bearish read. The code path is otherwise
   correct and tested (see `tests/test_regime.py`); this is a live upstream data
   gap, not a bug here. `backtest.py --regime-filter` fetches `^CASE30` with the
   same `period` you pass for the backtest itself, so it hits the identical gap -
   when the index has no usable history, every bar's regime comes back `None`
   and `backtest_ticker()` treats an unknown regime as "don't block" rather than
   "bearish" (an earlier version of this code got that backwards and would have
   silently zeroed out every trade whenever the index data was thin - worth
   knowing if you ever see `--regime-filter` produce suspiciously few trades).
6. Any BUY/SELL signals are sent to you as a single Telegram message, held positions
   first.

These parameters live in `thndr_bot/config.py` (`StrategyConfig`) if you want to
tune them.

## Backtesting — know what you're getting into first

Before trusting any of this, run the backtest: `python backtest.py --period 3y` (or
trigger the **Backtest** workflow from the Actions tab, since Yahoo Finance isn't
reachable from every environment). It walks the strategy forward bar-by-bar (no
lookahead) against real historical data and reports win rate, average/total return,
max drawdown, and a buy-and-hold comparison per ticker.

This is deliberately the *plain* version of the strategy after a round of testing
more sophisticated variants — worth knowing before you assume more complexity means
more accuracy:

- **A multi-indicator confluence filter** (requiring RSI + MACD + volume + Bollinger
  Band position to agree before firing) cut down whipsaws on a few names but also
  traded away some of the largest winners (one ticker's 3-year return went from
  +110% to -11% once confirmation caught up too late).
- **Forcing exits at the ATR stop-loss/take-profit** helped tickers that were
  losing money, but capped the strategy's best trend-following winners even harder
  (multiple tickers' 3-year returns dropped by 100+ percentage points) — a fixed,
  non-trailing stop held for a long time just waits to get clipped by an ordinary
  pullback in an otherwise-healthy uptrend.
- The plain crossover-in / crossover-out baseline outperformed both of those
  variants overall on this specific 3-year EGX sample, precisely because it lets
  losses cut naturally at the next death cross and winners run all the way to
  their own reversal, instead of an added rule doing it prematurely.

None of this means the baseline is *good* in an absolute sense — see the general
caveats above (small trade counts, no fundamentals/news awareness, EGX's multi-year
uptrend meaning even buy-and-hold often beat every variant tested). It's the
best-supported option among what's been tried here, not a guarantee. `backtest_ticker()`
still accepts `use_stop_loss_exit=True` / `use_take_profit_exit=True` if you want to
re-run that comparison yourself, and the ATR levels are always computed and shown
in alerts even though nothing acts on them automatically.

### Checking for overfitting

Everything above was validated by repeatedly backtesting the same 3-year window,
which risks tuning to that specific stretch rather than anything that generalizes.
Run `python backtest.py --split 0.6` to backtest the first 60% of the period
in-sample and the last 40% out-of-sample separately, with a pooled (trade-weighted)
win rate and average return for each half. The last run showed a real drop
out-of-sample (pooled win rate 49.1% in-sample vs. 31.0% out-of-sample, average
return/trade 6.8% vs. 2.4%) — a reminder to treat any single full-period backtest
number with real skepticism, and to re-run this split check after any future
strategy change.

### Market-regime filter (untested in production, available for comparison)

`python backtest.py --regime-filter` (composable with `--split`) only takes BUY
signals while EGX30 is above its own 200-day SMA, and reports the same metrics as
the plain backtest so you can compare. Given the track record above — every gating
rule tried so far has underperformed just trading the crossover directly — don't
assume this one will be different until you've actually looked at the numbers.

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

### Tracking real profit/loss

Optionally set `"cost_basis"` (your average purchase price per share, EGP) and
`"quantity"` (shares held) on a held ticker. When present, alerts show your actual
unrealized P&L — e.g. `Your position: cost 30.00 → now 42.00 (+40.0%), +120.00 EGP
on 10 shares` — instead of just the bare signal price. Both are optional and default
to `null`; the bot works fine without them, you just lose that context in the alert.

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
  strategy.py                   SMA-crossover + RSI signal logic, plus reference-only
                                 ATR stop-loss/take-profit levels
  regime.py                     EGX30 bullish/bearish regime context (informational)
  backtest.py                   walk-forward trade simulator + performance metrics,
                                 walk-forward split, and regime-filter comparison
  notifier.py                   Telegram sending
  runner.py                     orchestrates fetch -> signal -> notify for the watchlist
config/watchlist.json           tickers to track (edit this to change coverage)
tests/                          unit tests for signal logic and the backtest simulator
.github/workflows/egx-signal-bot.yml   scheduled live run via GitHub Actions
.github/workflows/backtest.yml         on-demand backtest run via GitHub Actions
```
