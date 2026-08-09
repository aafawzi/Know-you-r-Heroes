from datetime import date

import pytest

from thndr_bot.costs import (
    EGX_FEE_MAX_EGP,
    EGX_FEE_RATE,
    FRA_MAX_EGP,
    FRA_MIN_EGP,
    FRA_RATE,
    MCDR_MAX_EGP,
    MCDR_RATE,
    NCRF_MIN_EGP,
    NCRF_RATE,
    STAMP_DUTY_LAW_EFFECTIVE,
    STAMP_DUTY_RATE,
    STAMP_DUTY_SAME_DAY_ROUND_TRIP_RATE,
    THNDR_COMMISSION_FIXED_EGP,
    THNDR_COMMISSION_RATE,
    round_trip_cost_egp,
    round_trip_cost_pct,
    side_cost_egp,
)

BEFORE_LAW = date(2026, 7, 28)
ON_LAW = STAMP_DUTY_LAW_EFFECTIVE
AFTER_LAW = date(2026, 8, 9)


def test_side_cost_sums_every_component_at_a_mid_size_notional():
    # 20,000 EGP is comfortably clear of every min/max cap, so every
    # component's plain rate applies with no clamping - the simplest case
    # to hand-check.
    notional = 20_000.0
    expected = (
        THNDR_COMMISSION_FIXED_EGP
        + notional * THNDR_COMMISSION_RATE
        + notional * FRA_RATE
        + notional * EGX_FEE_RATE
        + notional * NCRF_RATE
        + notional * MCDR_RATE
        + notional * STAMP_DUTY_RATE
    )
    assert side_cost_egp(notional, AFTER_LAW) == pytest.approx(expected)


def test_side_cost_has_no_stamp_duty_before_the_law_took_effect():
    notional = 20_000.0
    before = side_cost_egp(notional, BEFORE_LAW)
    after = side_cost_egp(notional, AFTER_LAW)
    assert after - before == pytest.approx(notional * STAMP_DUTY_RATE)


def test_stamp_duty_applies_on_the_effective_date_itself():
    notional = 20_000.0
    on_date = side_cost_egp(notional, ON_LAW)
    before = side_cost_egp(notional, BEFORE_LAW)
    assert on_date - before == pytest.approx(notional * STAMP_DUTY_RATE)


def test_fra_floor_binds_on_a_tiny_trade():
    # At 100 EGP notional, 0.00625% is a few hundredths of a piaster -
    # nowhere near the EGP 1 floor, so the floor must be what's charged.
    notional = 100.0
    cost = side_cost_egp(notional, BEFORE_LAW)
    commission = THNDR_COMMISSION_FIXED_EGP + notional * THNDR_COMMISSION_RATE
    egx = notional * EGX_FEE_RATE
    ncrf = max(notional * NCRF_RATE, NCRF_MIN_EGP)
    mcdr = notional * MCDR_RATE
    assert cost == pytest.approx(commission + FRA_MIN_EGP + egx + ncrf + mcdr)


def test_ncrf_floor_binds_on_a_tiny_trade():
    notional = 10.0
    cost = side_cost_egp(notional, BEFORE_LAW)
    commission = THNDR_COMMISSION_FIXED_EGP + notional * THNDR_COMMISSION_RATE
    fra = max(notional * FRA_RATE, FRA_MIN_EGP)
    egx = notional * EGX_FEE_RATE
    mcdr = notional * MCDR_RATE
    assert cost == pytest.approx(commission + fra + egx + NCRF_MIN_EGP + mcdr)


def test_fra_egx_mcdr_ceilings_bind_on_a_huge_trade():
    # 100M EGP notional is far beyond retail position sizing, but it's the
    # clean way to prove the ceilings are wired up at all.
    notional = 100_000_000.0
    cost = side_cost_egp(notional, BEFORE_LAW)
    commission = THNDR_COMMISSION_FIXED_EGP + notional * THNDR_COMMISSION_RATE
    ncrf = notional * NCRF_RATE
    assert cost == pytest.approx(commission + FRA_MAX_EGP + EGX_FEE_MAX_EGP + ncrf + MCDR_MAX_EGP)


def test_side_cost_rejects_negative_notional():
    with pytest.raises(ValueError):
        side_cost_egp(-1.0, AFTER_LAW)


def test_round_trip_is_the_sum_of_both_sides_when_not_same_day():
    entry_cost = side_cost_egp(20_000.0, AFTER_LAW)
    exit_cost = side_cost_egp(21_000.0, date(2026, 8, 12))
    total = round_trip_cost_egp(20_000.0, 21_000.0, AFTER_LAW, date(2026, 8, 12))
    assert total == pytest.approx(entry_cost + exit_cost)


def test_round_trip_same_day_before_the_law_is_unaffected_by_the_discount():
    # Stamp duty is zero pre-law either way, so a same-day round trip should
    # cost exactly two ordinary side costs - the discount branch has nothing
    # to discount yet.
    normal = side_cost_egp(20_000.0, BEFORE_LAW) + side_cost_egp(20_000.0, BEFORE_LAW)
    same_day = round_trip_cost_egp(20_000.0, 20_000.0, BEFORE_LAW, BEFORE_LAW)
    assert same_day == pytest.approx(normal)


def test_round_trip_same_day_after_the_law_uses_the_discounted_stamp_rate():
    notional = 20_000.0
    same_day = round_trip_cost_egp(notional, notional, AFTER_LAW, AFTER_LAW)
    overnight = round_trip_cost_egp(notional, notional, AFTER_LAW, date(2026, 8, 10))
    # Overnight pays full stamp duty (0.05%) on each of the two legs, i.e.
    # 0.10% of notional combined. Same-day pays a single combined 0.025% of
    # notional for the whole round trip instead - see the interpretation
    # note in costs.round_trip_cost_egp.
    overnight_stamp = notional * STAMP_DUTY_RATE * 2
    same_day_stamp = notional * STAMP_DUTY_SAME_DAY_ROUND_TRIP_RATE
    assert overnight - same_day == pytest.approx(overnight_stamp - same_day_stamp)


def test_round_trip_cost_pct_matches_egp_cost_divided_by_entry_notional():
    entry_notional = 20_000.0
    exit_notional = 22_000.0
    egp = round_trip_cost_egp(entry_notional, exit_notional, AFTER_LAW, date(2026, 8, 12))
    pct = round_trip_cost_pct(entry_notional, exit_notional, AFTER_LAW, date(2026, 8, 12))
    assert pct == pytest.approx(egp / entry_notional * 100)


def test_round_trip_cost_pct_rejects_non_positive_entry_notional():
    with pytest.raises(ValueError):
        round_trip_cost_pct(0.0, 100.0, AFTER_LAW, AFTER_LAW)


def test_accepts_datetime_like_objects_as_well_as_plain_dates():
    import pandas as pd

    notional = 20_000.0
    via_date = side_cost_egp(notional, AFTER_LAW)
    via_timestamp = side_cost_egp(notional, pd.Timestamp(AFTER_LAW))
    assert via_date == pytest.approx(via_timestamp)
