# EGX Quantitative System — Project Discovery & Architecture Report

**Date:** 2026-08-09
**Status:** Phase 1 (Discovery). No new system code written yet, by design.
**Evidence standard:** every external dependency below is labelled
**VERIFIED** (I called it and saw the response), **DOCUMENTED** (a credible
source describes it; I could not call it myself), or **NEEDS TESTING**
(plausible but unproven). Nothing is labelled from assumption alone.

Reproduce the VERIFIED rows with `scripts/probe_sources.py` (run via the
**Probe Data Sources** workflow). Raw evidence lives in that run's log.

---

## 0. Executive summary — the five things that actually matter

1. **The official EGX WebService is real, undocumented, and far better than
   Yahoo for indices.** It returned **2,422 daily EGX30 closes back to
   2016-08-14 — ten years** — plus intraday ticks for the current session. This
   fixes the market-regime engine, which is dead today because Yahoo refuses to
   serve `^CASE30` history. **VERIFIED.**
2. **There is an official `EGX_33_Shariah` index**, screened to AAOIFI-style
   rules by EGX's own Shariah board, and its history is available from the
   same endpoint. This should anchor the Sharia universe instead of the
   hand-rolled sector-exclusion list currently in `config/watchlist.json`.
   Index **VERIFIED**; constituent list **NEEDS TESTING**.
3. **Realistic round-trip cost is ≈0.40% of notional plus EGP 4**, and the
   tax regime *changed on 29 July 2026* (Law 153/2026 reinstated stamp duty).
   The current backtest models **zero costs**, so every performance number
   produced so far is optimistic. **DOCUMENTED.**
4. **Equity data is adequate; index and breadth data are the gap.** Yahoo
   gives clean daily OHLCV in EGP for EGX equities (495 bars / 2y) but has no
   usable index history and silently omits some listings entirely.
   **VERIFIED.**
5. **The hard problem is not engineering, it's edge.** Work already done in
   this repo shows the existing signal lost to buy-and-hold on 12 of 13 held
   positions and degraded badly out-of-sample. Sections 15–30 of the brief
   (news/social intelligence) are the most expensive to build and the least
   proven; they should be sequenced *after* a cheap test of whether they
   predict anything.

---

## 1. Environment constraint discovered first (affects everything below)

| Finding | Status |
|---|---|
| Dev container egress is an **allowlist** — GitHub, PyPI, npm, Anthropic only. All other hosts return `HTTP 403` at the CONNECT tunnel. | VERIFIED |
| `WebFetch` is **also** egress-blocked, including `en.wikipedia.org`. | VERIFIED |
| `WebSearch` works. | VERIFIED |
| GitHub Actions runners have **unrestricted** network. | VERIFIED |

**Consequence:** no data-source code can be developed or tested locally. Every
integration must be verified through CI. This is why `scripts/probe_sources.py`
exists and why it should stay in the repo permanently — it is the only way to
answer "is this source still alive?" It also means the eventual production
runtime should be CI/cron-based (as today) or a small VPS, not a local machine.

---

## 2. Historical & current market data

### 2.1 Official EGX WebService — `https://www.egx.com.eg/WebService.asmx`

Discovered by reading the source of the `egx` PyPI package (v0.3.0, MIT,
`abed8080/egx`) rather than trusting its README. The package is a thin wrapper
over one undocumented ASP.NET endpoint.

`GET /getIndexChartData?index={INDEX}&period={DAYS}&gtk=0` → JSON array of
`{CDAY, INDEX_VALUE}`.

Results pooled over two independent sweeps (a source this flaky cannot be
characterised from one run):

| Probe | Result | Status |
|---|---|---|
| `EGX30`, period=0 | 61 rows, `09:58 → 14:55` same day — **intraday** | VERIFIED |
| `EGX30`, period=1825 | 1,210 rows, 2021-08-11 → 2026-08-06 | VERIFIED |
| `EGX30`, period=3650 | **2,422 rows, 2016-08-14 → 2026-08-06 (10 years)** | VERIFIED |
| `EGX70_EWI`, period=365 | 242 rows | VERIFIED |
| `EGX100_EWI`, period=365 | 242 rows | VERIFIED |
| `EGX_33_Shariah`, period=365 | 242 rows | VERIFIED |
| `EGX30_CAP`, period=365 | 242 rows | VERIFIED |
| `EGXVolatility`, period=365 | 242 rows | VERIFIED |

Every supported index returned data. **Ten years of daily EGX30 closes is
enough history for genuine regime work and multi-cycle walk-forward testing** —
a large upgrade over the 3-year Yahoo-equity window used so far.

**Reliability — quantified, and the most operationally important finding here.**
Failures are *not* deterministic by parameter. The same call that fails once
succeeds seconds later; `period=3650` and `EGXVolatility` both failed in sweep 1
and succeeded in sweep 2. A dedicated 5× retry probe on one fixed call gave:

```
Reliability EGX30 p=365 x5 → 4/5 ok | ['30.6s/ERR', '1.3s/242r', '1.0s/242r', '1.3s/242r', '1.3s/242r']
```

So: **~20–25% transient failure rate, fully recovered by retry.** Successes
return in ~1.0–1.3 s; failures burn a 30 s timeout or reset the connection.
The whole `egx.com.eg` host behaves this way, not just this endpoint — the
homepage failed in one sweep and returned HTTP 200 in the other.

**Design consequences (non-optional):** retry with backoff, a generous timeout,
a local cache of the last good pull, and a rule that a single failure is never
interpreted as "no data" — that misreading is exactly what would make a regime
engine silently flip to "unavailable" or, worse, to a wrong state.

**What it does *not* give:** only `datetime` + `value`. No OHLC, no volume, no
constituents, no per-stock data. Sufficient for regime and benchmark work;
insufficient for anything needing index OHLC.

**Wider API surface — unknown.** I tried to enumerate the `.asmx` operation
list programmatically and the extraction returned nothing (the help page served
21,985 bytes, so the page loaded; my link pattern simply didn't match its
markup). **I therefore cannot say what else this service exposes** — there may
be per-stock or disclosure endpoints, or there may not. Recorded as
**NEEDS TESTING**, not as "no other operations exist".

**Terms of service — unresolved.** This is an internal endpoint powering EGX's
own charts, not a published API. There is no documented rate limit or licence.
Polite use (daily pull, cached, backed off, identifiable UA) is low-risk, but
**this is a dependency that can vanish without notice and without recourse.**
Treat it as a convenience, keep the fallback path warm, and do not build
anything commercial on it without contacting EGX.

### 2.2 Yahoo Finance — equities

| Probe | Result | Status |
|---|---|---|
| `COMI.CA`, `SWDY.CA`, `ETEL.CA`, `TMGH.CA`, `ISPH.CA` @ 2y | 495 bars each, full OHLCV, currency **EGP** | VERIFIED |
| `GOUR.CA` | HTTP 404 "may be delisted" | VERIFIED |
| `BONY.CA` | HTTP 404 "may be delisted" | VERIFIED |

Yahoo is good enough for daily equity OHLCV and is already in production here.
Its weaknesses are real: **silent omissions** (GOUR is a genuine 2026 listing,
not delisted — Yahoo simply lacks it; BONY likewise), unknown corporate-action
adjustment policy, and no SLA.

### 2.3 Yahoo Finance — indices (do not use)

| Probe | Result | Status |
|---|---|---|
| `^CASE30` @ 5d **and** @ 2y | **1 bar** in both cases | VERIFIED |
| `^EGX30.CA` @ 5d / 2y | HTTP 200, **0 bars** | VERIFIED |
| `EGX30.CA` | HTTP 404 | VERIFIED |

This is the root cause of the currently-broken regime feature. It is an
upstream data gap, not a bug in this repo. **Replace with §2.1.**

### 2.4 Other surfaces (reachability only — no data contract tested)

| Source | Result | Status |
|---|---|---|
| `egx.com.eg/en/homepage.aspx` | HTTP 200, 49 KB (sweep 1); timeout (sweep 2) | VERIFIED, flaky |
| `egx.com.eg` (bare host) | Reset (sweep 1); HTTP 200, 50 KB (sweep 2) | VERIFIED, flaky |
| `WebService.asmx` help page | HTTP 200, ~21 KB | VERIFIED |
| **EGX 33 Shariah constituents page** | **HTTP 200, 83.9 KB** | VERIFIED reachable (parsing untested) |
| EGX 30 constituents page | Connection reset | Flaky — retry |
| Mubasher Egypt | HTTP 200, 415 KB | VERIFIED (reachable) |
| Investing.com | **HTTP 403** — bot-blocked | VERIFIED (unusable without scraping defences) |
| FRA (`fra.gov.eg`) | HTTP 200, 284 KB | VERIFIED (reachable) |
| CBE (`cbe.org.eg`) | HTTP 200, 231 KB | VERIFIED (reachable) |
| EODHD, Twelve Data | HTTP 200 | VERIFIED (reachable only) |

### 2.5 Commercial providers — NOT verified

EODHD, Twelve Data, ICE and **EGXAPI** (`egxapi.com`, which the brief named)
all advertise EGX coverage. I could not evaluate any of them: their sites are
egress-blocked from here, and all require paid keys, so coverage depth, history,
corporate-action handling and rate limits are **unverified**.

**Status: NEEDS TESTING.** Do not design around them yet. The concrete next
step is a free-tier key for one provider and a probe comparing its EGX history
against Yahoo bar-for-bar. EGXAPI additionally advertises *order routing*,
which is out of scope until the brief's live-execution phase.

---

## 3. Sharia compliance — the most important architectural change

**Current state in this repo is weak and self-admittedly so:** the watchlist is
a hand-made list built by excluding obvious sectors, with a disclaimer saying it
is "NOT a certified Sharia screening".

**Better primary source exists.** EGX publishes the **EGX 33 Shariah Compliant
Index**: 33 liquid constituents drawn from EGX100, each with a Sharia
supervisory board, vetted by an independent Shariah board, capped at 15% weight.
Screening follows AAOIFI-style rules — halal core activity, debt < 33% of market
cap, cash + receivables < 33%, prohibited revenue < 5%. *(DOCUMENTED via EGX,
FRA and market sources; the index's price history is VERIFIED via §2.1.)*

**Proposed compliance hierarchy:**

1. **Primary — official EGX 33 Shariah membership.** Authoritative, maintained
   by a real Shariah board, and revised periodically. Maps directly onto the
   brief's `COMPLIANT` bucket.
2. **Secondary — independent AAOIFI-style ratio screen** from fundamentals,
   used to *cross-check* the official list and to classify stocks outside it.
   Requires balance-sheet data (see §4) — currently the weakest input.
3. **Tertiary — manual override**, config-only, with reason and timestamp
   recorded, per the brief's audit-trail requirement.

Anything unresolved → `UNKNOWN` → **no BUY signal**, per §7 of the brief.

**Honest caveats:**
- Index membership is a *point-in-time* fact. Using today's list to screen a
  2021 backtest is textbook **survivorship/look-ahead bias** (§13 below).
  Historical constituent lists are **NEEDS TESTING** — if unavailable, Sharia-
  filtered backtests before the earliest snapshot we capture are not credible,
  and we should say so rather than quietly run them.
- Index inclusion also encodes a *liquidity* filter, which conveniently overlaps
  the brief's §9 but means "compliant but illiquid" names are invisible.
- The 33-name universe is small. That is a feature for risk, but it sharply
  limits how much signal research can be done without overfitting.

**Constituent page is reachable** — `currentindexconstituntes.aspx?type=22`
returned **HTTP 200, 83.9 KB**. Extracting the 33 tickers from that HTML is the
obvious Phase-3 task and is **NEEDS TESTING** (reachable ≠ parsed).

---

## 4. Fundamentals — the biggest genuine gap

No verified free source of EGX company financials was found. This directly
constrains:

- the independent AAOIFI ratio screen (§3),
- the `FUNDAMENTAL_SCORE` in brief §14,
- any valuation overlay.

Options, none verified: EODHD/commercial (paid, coverage unknown), company IR
PDFs (Arabic, unstructured, no API), EGX disclosure filings (see §5).

**Recommendation:** treat §14 as **deferred**, not designed. Building a
fundamental score on unverified data would violate the brief's own rule against
fabricating financial data.

---

## 5. Disclosures, news and social — scope reality check

| Requirement | Reality | Status |
|---|---|---|
| EGX official disclosures | Site reachable; a structured feed is unproven | NEEDS TESTING |
| FRA / CBE announcements | Sites reachable; no API found | NEEDS TESTING |
| Financial media | Mubasher reachable; Investing.com bot-blocked (403) | Mixed |
| X/Twitter | API is paid and restrictive; free scraping violates ToS | DOCUMENTED — likely blocked |
| Facebook / Telegram private groups | Explicitly out of bounds per brief §19 | Excluded |
| Reddit / YouTube | Public APIs exist | NEEDS TESTING |
| Arabic + Egyptian-Arabic + Arabizi NLP | Hard; models exist but entity resolution to EGX tickers is bespoke | NEEDS TESTING |

**This is where I most strongly diverge from the brief's ordering.** Sections
15–30 describe roughly half the system's surface area and are the most
expensive things in it. Before building a rumour engine, a manipulation
detector, a source-track-record store and an Arabic NLP pipeline, we should
spend a fraction of that effort answering: *does any of this predict returns on
EGX?* The brief itself says "Do not assume social sentiment has predictive
value. Prove it." (§44). Proving it needs only a modest event-study harness
plus a few months of collected data — not the full engine.

**Also note a chicken-and-egg problem the brief doesn't address:** historical
social data is largely unavailable retrospectively. Social backtesting (§44)
therefore cannot start until we have collected data *forward* for months. Any
plan that assumes we can backtest social signals on day one is wrong.

---

## 6. Trading costs — concrete, and recently changed

Per-side, EGX + Thndr *(DOCUMENTED from Thndr support and EGX fee schedule;
verify against a real contract note before trusting to the basis point)*:

| Component | Rate |
|---|---|
| Thndr commission | EGP 2 per order + 0.10% |
| FRA/EFSA | 0.00625% (min EGP 1, max EGP 250) |
| EGX | 0.012% (max EGP 5,000) |
| Non-Commercial Risk Fund | 0.02% (min EGP 0.05) |
| MCDR | 0.0125% (max EGP 5,000) |
| **Stamp duty (from 29 Jul 2026)** | **0.05%** (0.025% same-day round trip) |

≈ **0.20% per side → ~0.40% round trip, plus ~EGP 4 fixed.**

**Two consequences the brief's §41 demands we honour:**

1. **The existing backtest models no costs at all.** At ~0.40% round trip, the
   baseline's +5.6% average return per trade becomes ~+5.2%, and the 3-ATR
   trailing variant's +1.6% becomes ~+1.2% — a quarter of its edge. Any future
   comparison must net costs before drawing conclusions.
2. **The cost regime changed mid-sample.** Law 153/2026 (in force 29 July 2026)
   reinstated stamp duty and made listed-equity capital gains income-tax exempt.
   A 3–5 year backtest spans *two different tax regimes*, so a single flat cost
   assumption is wrong. Model costs as a function of trade date.

Fixed EGP 2/order also means **small positions are disproportionately taxed** —
this interacts with position sizing (§37 of the brief) and argues for a minimum
position value.

---

## 7. Data-quality, corporate actions, survivorship

- **Corporate actions:** Yahoo's adjustment policy for EGX is undocumented and
  unverified. Egypt has frequent bonus issues and capital increases. An
  unadjusted or wrongly-adjusted series manufactures fake gaps that look like
  breakouts. **This is the single most likely source of silent backtest
  corruption.** Mitigation: cross-provider comparison (§4 of the brief) and an
  explicit `corporate_actions` table; where we cannot confirm, mark the series
  `WARNING` and refuse high-confidence signals.
- **Survivorship:** today's watchlist applied to 2021 data is biased. GOUR
  (2026 listing) is a live example already in our universe.
- **Look-ahead:** the existing engine is clean here (bar-by-bar, verified by
  tests), and that discipline must carry into the new one. Note the subtle trap
  already documented in this repo: a crossover SELL fires *at* the collapsed
  price, so "the signal got me out before the drop" is usually false.

---

## 8. Recommended technology stack

The brief's proposal is reasonable; I'd trim it.

| Layer | Recommendation | Note |
|---|---|---|
| Language | Python 3.11+ | Already in use |
| Data | pandas | Polars is premature at this data size |
| Storage | **SQLite → Postgres later** | 33–200 tickers × daily bars is megabytes, not gigabytes. Postgres now is ceremony. |
| Scheduling | GitHub Actions (already proven) | Only network-capable environment available |
| Dashboard | **Defer.** Telegram + a static HTML report first | A dashboard is a consumer of signals that don't yet have proven value |
| API layer | **Defer.** No second consumer exists yet | FastAPI for a single user is overhead |
| Notifications | Telegram (already working) | Reuse |

**Deliberate divergences from the brief:** Postgres, FastAPI, Streamlit and the
dashboard are all deferred. They are the most visible parts of the system and
among the least load-bearing; building them early converts effort into surface
area rather than into evidence.

---

## 9. Proposed architecture

Close to the brief's, collapsed where the split buys nothing today:

```
src/
  data/providers/        base, egx_webservice, yahoo, fallback
  data/quality/          validators, status enum, cross-provider diff
  market/                calendar, universe, corporate_actions
  sharia/                official_index, aaoifi_screen, overrides, audit
  features/              trend, momentum, volume, relative_strength
  regime/                EGX30/EGX70 breadth + trend classification
  strategies/            one module per testable setup
  signals/               scoring, generation, explanation
  risk/                  sizing, stops, portfolio limits
  backtest/              engine, costs (date-aware), metrics, walkforward
  paper/                 simulated broker + portfolio
  notifications/         telegram
  intelligence/          (Phase 7+, deliberately last)
```

The one structural thing worth building **now**, before features: the
**provider abstraction with quality status**, because it is the thing that is
painful to retrofit and the thing our verification says we most need (two
sources, both flaky in different ways).

---

## 10. Roadmap (re-sequenced, with rationale)

The brief's 13 phases are sound in spirit. My changes are ordering and honesty
gates, not scope deletion.

| Phase | Work | Gate before proceeding |
|---|---|---|
| 1 ✅ | Discovery (this document) | — |
| 2 | Provider abstraction + quality engine + SQLite; migrate regime to EGX WebService | Regime reports bullish/bearish from real data |
| 3 | Sharia universe from official EGX 33 + audit trail | Universe reproducible, point-in-time caveat documented |
| 4 | **Date-aware cost model + re-run every existing backtest net of costs** | We know what we actually have, post-costs |
| 5 | Regime, relative strength, volume, liquidity score | Each tested for incremental value |
| 6 | Baseline strategies + walk-forward | **Beats buy-and-hold net of costs, out-of-sample** |
| 7 | Risk engine + paper trading | Paper portfolio runs unattended |
| 8 | Official disclosures only (Tier 1) | Disclosure feed proven parseable |
| 9 | **Event-study harness** — measure whether news/social predicts anything | Positive evidence, else stop |
| 10+ | Social intelligence, rumour/manipulation engines, dashboard, ML | Only past the gate above |

**Phase 4 is the one I would not skip.** It is cheap and it re-prices every
conclusion this project has reached so far.

---

## 11. Costs

| Item | Cost |
|---|---|
| Yahoo + EGX WebService | Free (no SLA, no licence) |
| GitHub Actions | Free tier is sufficient for daily runs |
| SQLite | Free |
| Telegram | Free |
| **Subtotal to Phase 8** | **≈ EGP 0** |
| Commercial market data (if needed) | ~$20–100/mo |
| X/Twitter API (if social pursued) | ~$100+/mo |
| LLM calls for Arabic NLP | Usage-based |

The evidence-gathering half of this project costs nothing. The unproven half is
where the money is. That asymmetry should drive sequencing.

---

## 12. Self-critique (brief §66)

Arguing against my own design:

**As a quant researcher.** The most likely outcome is that no combination of
these features beats buy-and-hold on EGX net of costs. The evidence already in
this repo points that way: five exit-rule variants all lost to a plain
crossover, the strategy lost to holding on 12 of 13 positions, and win rate fell
49.1% → 31.0% out-of-sample. Adding 15 more evidence sources to a system whose
core has negative demonstrated edge may just produce a better-decorated losing
strategy. *Mitigation:* the Phase-6 gate — beat buy-and-hold net of costs
out-of-sample, or stop.

**Statistical power.** 33 Sharia-compliant names × ~5 years is a small sample.
The brief asks to validate ~15 signal components with interaction effects on
it. There is not enough independent data to do that honestly; we will find
spurious structure. *Mitigation:* few parameters, wide stable regions, and
treat any result from >2–3 tuned knobs as unproven.

**As a data engineer.** Two flaky, undocumented, ToS-ambiguous sources underpin
everything. The EGX endpoint reset ~4 times in one 20-request sweep. Yahoo
silently omits real listings. *Mitigation:* the quality engine is not optional,
and the system must degrade to "no signal" rather than "bad signal".

**As a Sharia reviewer.** Point-in-time compliance is the honest weak spot. We
can state today's status confidently from the official index; we largely cannot
reconstruct 2022's. Any historical Sharia-filtered backtest is therefore
contaminated unless we start snapshotting now. *Mitigation:* begin storing
constituent snapshots immediately — it costs nothing today and is impossible to
recover later.

**As a security engineer.** Secrets are already in GitHub Actions secrets, not
files — good. But a Telegram command channel that mutates portfolio state
(already live in this repo) is an input surface: it is chat-ID-gated, which is
adequate for one user but is authentication by obscurity. Anything that ever
places orders needs materially stronger controls.

**As a trader.** ~0.40% round trip against a strategy holding for days-to-weeks
is a real drag. Fixed EGP 2/order penalises small positions. And EGX liquidity
means a signal on a thin name may be unfillable at the modelled price — the
liquidity score must gate signals, not merely annotate them.

**Is this over-complicated?** Yes, as specified. The brief describes a system
whose intelligence layer is larger than its evidence base. The version I
recommend building first is perhaps 20% of the spec: reliable data, an official
Sharia universe, a working regime, honest costs, and one or two strategies
measured properly against buy-and-hold. If that clears the bar, the rest is
justified. If it doesn't, the rest would have been decoration on a losing bet.

---

## 13. Decisions taken (2026-08-09)

**1. The Phase-6 gate is accepted.** A strategy must **beat buy-and-hold, net
of costs, out-of-sample** or the project stops rather than proceeds to the
intelligence layer. This is now a binding condition, not an aspiration, and it
determines the build order below: costs and a real benchmark come *before*
anything that generates signals.

**2. Budget is zero.** No paid data. The consequences are concrete and worth
stating plainly rather than discovering later:

| Consequence | Effect |
|---|---|
| No commercial provider (EODHD / Twelve Data / EGXAPI) | Cross-provider validation (brief §4) degrades to *internal* consistency checks against a cached history. Real provider-disagreement detection is not achievable. |
| **No verified fundamentals source** | Brief §14 `FUNDAMENTAL_SCORE` is **cancelled**, not deferred. Building it on unverified data would break the brief's own rule against fabricating financial data. |
| No fundamentals ⇒ no ratio screen | **Independent AAOIFI screening is cancelled.** The official EGX 33 Shariah index becomes the *sole* compliance source, not a primary-with-cross-check. |
| No paid social APIs | X/Twitter is out. Any future social work is limited to genuinely public, ToS-compliant surfaces. |

**The Sharia consequence deserves emphasis.** With one source and no
independent verification, the system's compliance guarantee is exactly "EGX's
Shariah board says so, as of the last snapshot we took." That is a *reasonable*
guarantee — it is an accountable, qualified body — but it is single-sourced,
point-in-time, and cannot be reconstructed historically. The system must state
this to the user rather than implying it has performed its own screen. Every
signal should carry the snapshot date its compliance claim rests on.

**Deferred, not cancelled:** liquidity scoring, regime, relative strength and
paper trading all work on free data and stay in scope.

## 14. Immediate build order (Phase 2 onward)

Driven by the gate: the shortest path to a *trustworthy verdict*, not to a
feature-complete system.

1. **EGX index provider** — official endpoint, retry + cache + quality status.
   Unlocks 10y of EGX30 and fixes the dead regime feature. *Also supplies the
   benchmark the gate is measured against.*
2. **Date-aware cost model** — pre/post 29 Jul 2026 regimes; re-price every
   existing backtest conclusion.
3. **Sharia universe** from the official EGX 33 constituents, with snapshot
   dates recorded from day one (impossible to recover retrospectively).
4. **Run the gate.** Baseline strategy vs buy-and-hold, net of costs,
   out-of-sample. Publish the answer whichever way it falls.

---

## 15. Probe re-run 2026-08-09 (third sweep)

Re-confirmed, and worth recording because a flaky source needs repeated
observation rather than a single reading:

| Finding | Result |
|---|---|
| `EGX30` period=3650 | **2,423 rows, 2016-08-14 → 2026-08-09** — ten years, reproducible |
| All seven indices at period=365 | 243 rows each, including `EGX_33_Shariah` |
| Yahoo EGX equities @ 2y | 493 bars, full OHLCV, EGP |
| Yahoo `^CASE30` @ 5d and 2y | still **1 bar** — permanently unusable for history |
| `GOUR.CA`, `BONY.CA` | still HTTP 404 |
| Investing.com | still HTTP 403 (bot-blocked) |

**Flakiness reconfirmed, and it moves around.** This sweep `period=0` and
`period=1825` failed while `365` and `3650` succeeded — the opposite pattern to
sweep 2. Both egx.com.eg homepages failed here having succeeded before. This is
the third independent confirmation that failures are transient and unrelated to
the request, and it is why the provider retries rather than trusting one call.

**Not yet answered:** the `.asmx` operation inventory and the six speculative
per-stock endpoint probes ran, but I did not read that section of the log this
session. So **"can the exchange serve per-stock prices?" remains open** — the
data to answer it is sitting in run 31319670642's log. That question decides
whether Yahoo can stop being the sole equity source, so it should be the first
thing picked up next.
