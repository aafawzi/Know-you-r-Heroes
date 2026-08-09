"""Date-aware EGX + Thndr round-trip trading costs.

Every backtest number in this repo before this module existed assumed
trading was free. docs/DISCOVERY.md §6 found that's off by roughly half a
percentage point per round trip - not enough to flip a strong edge, but
enough to have already erased a chunk of what looked like edge in results
already in this repo (+5.6% average return/trade -> ~+5.2% for the
baseline). The fee schedule below is DOCUMENTED (Thndr support + the EGX
fee schedule), not independently verified against a real contract note -
treat the basis-point precision accordingly.

Two things make this date-aware rather than a single flat rate:

1. Law 153/2026 (in force 29 Jul 2026) reinstated stamp duty, which did not
   apply before that date. A multi-year backtest spans both regimes, so a
   single flat cost assumption silently mixes them.
2. The reinstated stamp duty carries a same-day round-trip discount -
   0.025% total instead of 0.05% per side - so a strategy that round-trips
   within a single session is taxed differently from one that holds
   overnight.
"""

from __future__ import annotations

from datetime import date

THNDR_COMMISSION_FIXED_EGP = 2.0
THNDR_COMMISSION_RATE = 0.0010  # 0.10%

FRA_RATE = 0.0000625  # 0.00625%
FRA_MIN_EGP = 1.0
FRA_MAX_EGP = 250.0

EGX_FEE_RATE = 0.00012  # 0.012%
EGX_FEE_MAX_EGP = 5000.0

NCRF_RATE = 0.0002  # 0.02% (Non-Commercial Risk Fund)
NCRF_MIN_EGP = 0.05

MCDR_RATE = 0.000125  # 0.0125%
MCDR_MAX_EGP = 5000.0

# Law 153/2026, in force 29 Jul 2026: reinstated stamp duty. Zero before
# this date. See docs/DISCOVERY.md §6.
STAMP_DUTY_LAW_EFFECTIVE = date(2026, 7, 29)
STAMP_DUTY_RATE = 0.0005  # 0.05% per side
STAMP_DUTY_SAME_DAY_ROUND_TRIP_RATE = 0.00025  # 0.025% total, same-day only


def _as_date(value) -> date:
    return value.date() if hasattr(value, "date") else value


def side_cost_egp(notional_egp: float, trade_date) -> float:
    """EGP cost of one side (buy or sell) of a trade at the given notional value.

    Sums every fee-schedule component, each with its own min/max cap. Stamp
    duty is zero before STAMP_DUTY_LAW_EFFECTIVE and 0.05% of notional from
    that date onward.
    """
    if notional_egp < 0:
        raise ValueError("notional_egp must be non-negative")
    trade_date = _as_date(trade_date)

    commission = THNDR_COMMISSION_FIXED_EGP + notional_egp * THNDR_COMMISSION_RATE
    fra = min(max(notional_egp * FRA_RATE, FRA_MIN_EGP), FRA_MAX_EGP)
    egx = min(notional_egp * EGX_FEE_RATE, EGX_FEE_MAX_EGP)
    ncrf = max(notional_egp * NCRF_RATE, NCRF_MIN_EGP)
    mcdr = min(notional_egp * MCDR_RATE, MCDR_MAX_EGP)
    stamp = notional_egp * STAMP_DUTY_RATE if trade_date >= STAMP_DUTY_LAW_EFFECTIVE else 0.0

    return commission + fra + egx + ncrf + mcdr + stamp


def round_trip_cost_egp(
    entry_notional_egp: float,
    exit_notional_egp: float,
    entry_date,
    exit_date,
) -> float:
    """EGP cost of opening at entry_notional_egp and closing at exit_notional_egp.

    Each side's variable fees scale off its own notional - you pay 0.10% of
    what you actually bought, and separately 0.10% of what you actually
    sold. Only the stamp-duty same-day discount ties the two sides
    together, since that discount exists specifically to price a same-day
    round trip differently from holding overnight.
    """
    entry_date, exit_date = _as_date(entry_date), _as_date(exit_date)
    entry_cost = side_cost_egp(entry_notional_egp, entry_date)
    exit_cost = side_cost_egp(exit_notional_egp, exit_date)

    same_day_after_law = entry_date == exit_date and entry_date >= STAMP_DUTY_LAW_EFFECTIVE
    if same_day_after_law:
        # "0.05% (0.025% same-day round trip)" is read here as: the whole
        # round trip's stamp duty is 0.025% of notional, not 0.05% charged
        # on each leg - i.e. a discount on the combined charge, not a halved
        # per-leg rate. That reading isn't independently confirmed (see
        # docs/DISCOVERY.md §6, DOCUMENTED not VERIFIED); it's the more
        # natural reading of "same-day round trip" describing one
        # transaction cycle rather than each leg of it. Strip each side's
        # full-rate stamp duty and replace both with a single combined
        # charge on the round trip's average notional.
        entry_cost -= entry_notional_egp * STAMP_DUTY_RATE
        exit_cost -= exit_notional_egp * STAMP_DUTY_RATE
        round_trip_notional = (entry_notional_egp + exit_notional_egp) / 2
        entry_cost += round_trip_notional * STAMP_DUTY_SAME_DAY_ROUND_TRIP_RATE

    return entry_cost + exit_cost


def round_trip_cost_pct(
    entry_notional_egp: float,
    exit_notional_egp: float,
    entry_date,
    exit_date,
) -> float:
    """Round-trip cost as a percentage of the entry notional.

    This is the number that subtracts directly from a price return_pct -
    see thndr_bot.backtest.Trade.return_pct_net_of_costs.
    """
    if entry_notional_egp <= 0:
        raise ValueError("entry_notional_egp must be positive")
    cost = round_trip_cost_egp(entry_notional_egp, exit_notional_egp, entry_date, exit_date)
    return cost / entry_notional_egp * 100
