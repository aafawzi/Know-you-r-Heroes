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

> ### ⚠️ Read this before acting on a SELL alert
>
> Measured against the last 3 years of real EGX data, mechanically following
> these signals **would have cost you money versus doing nothing** on 12 of the
> 13 positions you hold. Treat the alerts as a prompt to go look at a position,
> not as an instruction to trade it. Full numbers in
> [Does acting on the signals beat doing nothing?](#does-acting-on-the-signals-beat-doing-nothing)

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
5. Every run also fetches the EGX30 index and computes whether it's
   above or below its own 200-day SMA - shown at the top of the Telegram message as
   market context (e.g. "Market: EGX30 bullish (vs 200-day avg)"). Like the ATR
   levels, this is **informational only** and doesn't gate any signal; see
   `backtest.py --regime-filter` below for whether gating on it would actually help.
   **Data source:** the EGX30 series comes from the exchange's own endpoint,
   not Yahoo. Yahoo serves exactly one bar for `^CASE30` no matter what range
   is requested (verified repeatedly), which is why this feature reported
   "unavailable" for a long time. The official endpoint returned 2,422 daily
   closes back to 2016. It is undocumented and fails ~20-25% of calls, so the
   provider retries with backoff and falls back to the last good pull - and a
   cached read is labelled "(stale data)" in the alert rather than passed off
   as current.
6. Every run sends you a single Telegram message with two parts:
   - **Your Portfolio** — every ticker marked `held: true`, always included whether
     or not it has a signal, showing current price and (if `cost_basis`/`quantity`
     are set) your unrealized P&L and a total across all held positions. This is
     what keeps your portfolio visible on every run, not just on signal days.
   - **Signals** — any BUY/SELL crossovers this run, held positions first (a SELL
     on something you own is more urgent than a BUY idea on something you don't).
   If there are no held positions and no signals, nothing is sent.

These parameters live in `thndr_bot/config.py` (`StrategyConfig`) if you want to
tune them.

## Does acting on the signals beat doing nothing?

This is the question that matters most, and it went unasked for a long time
while exit rules got tuned. `python backtest.py --vs-hold` answers it directly.
Because you already own these shares, "are these good entries?" is moot — the
live question is whether acting on a **SELL** alert beats sitting still. So it
reports three numbers per ticker over the same bars: buy-and-hold, the
entry-picking strategy, and *hold-with-signal-exits* (start invested, step out
on every SELL, step back in on the next BUY).

Over 3 years, on the 13 held positions with data:

| | Mean return | Beat buy-and-hold |
|---|---|---|
| Buy and hold | **206.2%** | — |
| Hold, exit on SELL alerts | 91.2% | **1 / 13** |
| Strategy (entries too) | 29.1% | 2 / 13 |

Per position, acting on the alerts versus doing nothing:

| Ticker | Buy & hold | Hold + signal exits | Cost of acting |
|---|---|---|---|
| ISPH | 612.2% | 172.9% | **−439.2** |
| CLHO | 331.1% | 69.2% | −261.9 |
| TMGH | 547.2% | 303.0% | −244.3 |
| MASR | 202.3% | 50.5% | −151.8 |
| TALM | 359.6% | 211.9% | −147.7 |
| RMDA | 337.8% | 269.8% | −68.0 |
| ETEL | 283.0% | 214.8% | −68.2 |
| ECAP | 92.0% | 26.7% | −65.3 |
| ABUK | 21.0% | −33.5% | −54.5 |
| AMOC | 20.9% | −6.8% | −27.7 |
| EGCH | 6.2% | −15.2% | −21.4 |
| SKPC | −39.7% | −43.3% | −3.6 |
| **MFPC** | **−92.6%** | **−34.5%** | **+58.1** |

One position out of thirteen. And look at *which* one: MFPC, the only holding
that genuinely collapsed. That's the honest shape of what this bot does — it
is not an edge, it's disaster insurance, and the premium is steep. You pay it
on every position that merely wobbles and keeps climbing.

Caveats that cut in the bot's favour, stated plainly:

- **This window is a huge EGX bull market** (mean buy-and-hold +206%). *Any*
  rule that steps out of the market looks terrible against that, and this
  result would look very different across a sustained bear market. It is
  evidence about this regime, not a universal verdict.
- The means are dragged around by outliers like ISPH; the 1-of-13 count is the
  robust number, and it doesn't depend on them.
- `hold_with_signal_exits()` starts invested on the first tradeable bar of the
  window, not at your actual entry dates or cost basis, so it measures
  "hold vs. time the exits over these 3 years" rather than replaying your
  account.

**What to do with that:** don't sell just because the bot says SELL. Use the
alert as a reason to open the chart and check whether something real is
happening — a genuine deterioration like MFPC, or ordinary noise in an uptrend
like ISPH. The bot is good at noticing that *something changed*; it is
demonstrably bad at telling you what to do about it.

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

### Trading costs (opt-in, net of fees)

Every number above is a *gross* price return — the backtest engine didn't
know trading costs exist until `thndr_bot/costs.py` was added. Pass
`--notional EGP` (e.g. `python backtest.py --notional 20000`) to also print
every result net of the documented EGX + Thndr round-trip fee schedule
(commission, FRA/EFSA, EGX fee, Non-Commercial Risk Fund, MCDR, and stamp
duty) for a position of that size, including whether the strategy still
beats buy-and-hold once *both* are netted of costs — buy-and-hold pays a
round trip too, so it isn't left at its gross number for the comparison.

Two things make this date-aware rather than a flat percentage: stamp duty
was reinstated by Law 153/2026 (in force 29 Jul 2026) and did not apply
before that date, and a same-day round trip is taxed at a discounted
combined rate rather than the full per-side rate. See `docs/DISCOVERY.md`
§6 and §18 for the sourcing and the specific interpretation choices made
where the fee schedule's wording was ambiguous — it's DOCUMENTED from
Thndr support and the EGX fee schedule, not independently verified against
a real contract note, so treat it as directionally right rather than exact
to the piaster.

### Trailing stop (tested, and still not enabled)

`python backtest.py --trailing-stop` exits at a stop that sits
`atr_trail_multiplier` ATRs (default 3) below the highest high reached since
entry and ratchets up only, never down. This was built specifically to fix why
the *fixed* stop failed — that one was set once at entry and sat there waiting
to be clipped by an ordinary pullback. Run head-to-head against the baseline on
the same 3-year window:

| | Baseline | Trailing stop |
|---|---|---|
| Closed trades | 103 | 116 |
| Pooled win rate | 41.7% | **47.4%** |
| Avg return/trade | **5.6%** | 1.6% |

It does exactly what a trailing stop is supposed to do, and that turns out not
to be enough. Win rate improves by ~6 points, losing positions bleed less
(MFPC -20.2% → -8.3%, AMOC -16.2% → -6.9%, ECAP -15.0% → -9.6%), and max
drawdowns drop sharply (AMOC 29.4% → 15.9%, MFPC 20.2% → 8.3%). More trades
end green and the ride is smoother.

But per-trade return collapses by ~70%, because this strategy's returns come
from a small number of very large winners, and a trailing stop truncates
exactly those. RMDA is the whole story in one row: **+113.8% total return
across 4 trades at a 75% win rate on the baseline, versus +3.4% across the same
4 trades at a 25% win rate with the trail on.** Same number of trades, each one
cut short at a worse price than the death cross would eventually have given.
Once the trail ejects you, getting back in needs a *fresh* golden cross — which
requires the fast SMA to fall back under the slow one first — so in a
persistent uptrend you can sit out the rest of the move entirely.

So it lands in the same place as the confluence filter and the fixed stop: a
rule that sounds prudent, measurably reduces volatility, and costs more in
forgone upside than it saves. **Live signals are unchanged** — the trailing
stop is opt-in for backtesting only.

#### Is 3 ATR just too tight? No — there's no sweet spot

`python backtest.py --trail-sweep 2 3 4 5 6 8 10` runs the baseline and every
width over a single data pull, so all rows see identical bars:

| Setting | Trades | WinRate% | AvgRet% | MeanTotalRet% | MeanMaxDD% | RMDA Total% |
|---|---|---|---|---|---|---|
| baseline (no trail) | 103 | 41.7 | **5.6** | **33.2** | 17.5 | **113.8** |
| 2 ATR | 117 | 47.0 | 1.4 | 9.5 | **6.7** | 15.9 |
| 3 ATR | 116 | 47.4 | 1.6 | 10.4 | 9.8 | 3.4 |
| 4 ATR | 114 | 40.4 | 1.4 | 9.4 | 13.4 | 1.8 |
| 5 ATR | 112 | 42.0 | 3.0 | 17.6 | 14.3 | 27.8 |
| 6 ATR | 112 | 38.4 | 2.8 | 17.6 | 15.3 | 79.8 |
| 8 ATR | 111 | 43.2 | 3.3 | 21.4 | 13.9 | 107.8 |
| 10 ATR | 111 | 41.4 | 4.6 | 27.7 | 16.8 | 113.8 |

Widening the trail doesn't find a better setting — it just slides a dial. Every
step wider gives back drawdown protection (6.7% → 16.8%) and buys back return
(9.5% → 27.7%), until at 10 ATR the stop barely fires at all and the whole
thing converges *to* the baseline (RMDA back to exactly 113.8%). There is no
width at which the trail beats simply not having one.

Risk-adjusted it's the same verdict. Return per unit of drawdown
(MeanTotalRet ÷ MeanMaxDD) is **1.90 for the baseline** and below it at every
single width — 1.42, 1.06, 0.70, 1.23, 1.15, 1.54, 1.65 — rising toward
baseline only as the trail stops mattering. So the trail isn't even buying
cheaper risk; it's strictly worse on that measure too.

One correction to the 3-ATR write-up above: the win-rate "improvement" doesn't
survive the sweep. Across widths it wanders between 38.4% and 47.4% with no
trend, landing *below* baseline at 4 and 6 ATR. On ~110 trades that spread is
noise, and the 47.4% at 3 ATR shouldn't be read as a real effect. The
systematic, reproducible effect is the one on drawdown — and its price is
return.

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
`"quantity"` (shares held) on a held ticker. When present, both the always-sent
portfolio summary and any BUY/SELL alert on that ticker show your actual unrealized
P&L — e.g. `ETEL (Telecom Egypt): 42.00 EGP | cost 30.00 → +40.0%, +120.00 EGP on 10
shares` — instead of just the bare price, and the portfolio summary totals P&L
across all positions that have both fields set. Both are optional and default to
`null`; the bot works fine without them, you just get price-only lines and no total.

### Keeping cost basis/quantity current after you buy or sell

The bot has no read access to your Thndr account, so nothing here updates
automatically when you trade — you tell it, either by editing
`config/watchlist.json` directly, or by messaging the bot in Telegram:

- `/update SYMBOL COST QTY` — set average cost and share count after any buy or
  sell (Thndr always shows both together as your new blended position, so send
  both every time). Also marks the ticker `held: true`. e.g. `/update TALM 21.50 60`.
- `/sell SYMBOL` — mark a position fully closed (clears cost basis/quantity,
  sets `held: false`).
- `/portfolio` — show current held positions and their stored cost basis/quantity.
- `/help` — list these commands.

A separate scheduled workflow (`.github/workflows/telegram-commands.yml`) polls
Telegram for new messages every 15 minutes, so a command doesn't take effect
instantly — expect up to a ~15-minute delay before the watchlist updates and
the next portfolio summary reflects it. Only messages from the `TELEGRAM_CHAT_ID`
configured in secrets are honored; anyone else who messages the bot is ignored,
since a command here can rewrite `config/watchlist.json`. Adding a brand-new
ticker isn't supported via chat (it needs a Yahoo symbol and company name) —
edit the JSON file directly for that, or ask for it to be added.

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
triggered manually from the Actions tab ("Run workflow"). `.github/workflows/backtest.yml`
runs `backtest.py` on demand (accepts a `period` input, e.g. `1y`/`3y`/`5y`) for when
you want fresh numbers without pulling the repo locally. `.github/workflows/telegram-commands.yml`
polls Telegram every 15 minutes for `/update`/`/sell`/`/portfolio` commands (see
"Keeping cost basis/quantity current" above) and commits any changes back to
`config/watchlist.json` — it needs `permissions: contents: write`, already set in
the workflow file, to push those commits.

To enable the scheduled bot:

1. In your GitHub repo, go to **Settings → Secrets and variables → Actions**.
2. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Push this repo to GitHub — the workflows run on their schedules automatically.

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
poll_commands.py                entry point for polling Telegram portfolio commands
thndr_bot/
  config.py                     env vars, strategy parameters, watchlist loader
  data.py                       Yahoo Finance price fetching
  strategy.py                   SMA-crossover + RSI signal logic, plus reference-only
                                 ATR stop-loss/take-profit levels
  regime.py                     EGX30 bullish/bearish regime context (informational)
  backtest.py                   walk-forward trade simulator + performance metrics,
                                 walk-forward split, and regime-filter comparison
  notifier.py                   Telegram sending
  commands.py                   Telegram /update, /sell, /portfolio command handling
  runner.py                     orchestrates fetch -> signal -> notify for the watchlist
config/watchlist.json           tickers to track (edit this to change coverage)
config/.telegram_offset.json    last processed Telegram update_id (auto-managed, do not edit)
tests/                          unit tests for signal logic, backtest simulator, and commands
.github/workflows/egx-signal-bot.yml      scheduled live run via GitHub Actions
.github/workflows/backtest.yml            on-demand backtest run via GitHub Actions
.github/workflows/telegram-commands.yml   polls for /update, /sell, /portfolio commands
```
