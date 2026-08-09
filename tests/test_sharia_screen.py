from thndr_bot.sharia import Financials, ShariaStatus, purification_due, screen


def _clean(**overrides) -> Financials:
    """A company comfortably inside every AAOIFI limit."""
    base = dict(
        market_cap=1000.0,
        interest_bearing_debt=100.0,  # 10%
        cash_and_interest_securities=100.0,  # 10%
        receivables=100.0,  # 10%
        total_revenue=500.0,
        non_compliant_revenue=0.0,
        period="FY2025",
        source="company annual report",
    )
    base.update(overrides)
    return Financials(**base)


# --- the default must be safe -------------------------------------------------


def test_no_information_yields_unknown_and_is_not_tradeable():
    result = screen("XXXX")

    assert result.status is ShariaStatus.UNKNOWN
    assert not result.tradeable


def test_unknown_is_not_tradeable_even_though_nothing_disqualified_it():
    # The whole point: absence of disqualifying evidence is not evidence of
    # compliance. Silence must never read as a pass.
    result = screen("XXXX", activities={"telecom"})

    assert result.status is ShariaStatus.UNKNOWN
    assert not result.tradeable


def test_partial_financials_refuse_to_conclude():
    # A zero market cap makes every ratio undefined. A half-done screen is
    # not a screen, so this must not fall through to COMPLIANT.
    result = screen("XXXX", financials=_clean(market_cap=0.0))

    assert result.status is ShariaStatus.UNKNOWN
    assert any("incomplete figures" in r for r in result.reasons)


# --- prohibited activity overrides everything ---------------------------------


def test_prohibited_activity_is_non_compliant_regardless_of_ratios():
    result = screen("BANK", activities={"conventional_banking"}, financials=_clean())

    assert result.status is ShariaStatus.NON_COMPLIANT
    assert not result.tradeable


def test_prohibited_activity_beats_official_index_membership():
    # If these ever disagree, the ban wins - no index listing can make a
    # brewery permissible.
    result = screen("XXXX", activities={"alcohol"}, in_official_index=True)

    assert result.status is ShariaStatus.NON_COMPLIANT


# --- the ratio screen ---------------------------------------------------------


def test_clean_financials_are_compliant():
    result = screen("XXXX", financials=_clean())

    assert result.status is ShariaStatus.COMPLIANT
    assert result.tradeable
    assert result.ratios["debt_to_market_cap"] == 0.10


def test_excess_debt_is_non_compliant():
    result = screen("XXXX", financials=_clean(interest_bearing_debt=400.0))  # 40% > 33%

    assert result.status is ShariaStatus.NON_COMPLIANT
    assert any("debt_to_market_cap" in r for r in result.reasons)


def test_small_impure_revenue_requires_purification_rather_than_exclusion():
    # 2% impure: permissible under AAOIFI, but the holder owes a donation,
    # so it must not be silently lumped in with fully clean companies.
    result = screen("XXXX", financials=_clean(non_compliant_revenue=10.0))  # 2%

    assert result.status is ShariaStatus.COMPLIANT_WITH_PURIFICATION
    # Not tradeable by default - it needs an explicit per-ticker opt-in.
    assert not result.tradeable


def test_impure_revenue_above_five_percent_is_non_compliant():
    result = screen("XXXX", financials=_clean(non_compliant_revenue=50.0))  # 10%

    assert result.status is ShariaStatus.NON_COMPLIANT


def test_ratio_just_inside_the_limit_is_borderline_not_a_clean_pass():
    # 31% debt passes 33% but could breach next filing. Flag for a look.
    result = screen("XXXX", financials=_clean(interest_bearing_debt=310.0))

    assert result.status is ShariaStatus.BORDERLINE
    assert not result.tradeable


# --- official index membership ------------------------------------------------


def test_index_membership_alone_is_compliant_but_records_its_limits():
    result = screen("XXXX", in_official_index=True, index_snapshot_date="2026-08-09")

    assert result.status is ShariaStatus.COMPLIANT
    assert result.tradeable
    assert "2026-08-09" in result.evidence[0]
    assert any("no independent ratio check" in r for r in result.reasons)


def test_absent_from_index_without_financials_stays_unknown():
    # "Checked and absent" is evidence, but it is not enough to condemn or
    # clear a company on its own.
    result = screen("XXXX", in_official_index=False)

    assert result.status is ShariaStatus.UNKNOWN
    assert "absent from EGX 33 Shariah constituents" in result.evidence


def test_disagreement_between_sources_is_surfaced_not_resolved_silently():
    # Listed in the index, but its current numbers breach the limits. The
    # index snapshot is probably stale - which is exactly what continuous
    # monitoring is meant to catch, so demand review instead of picking one.
    result = screen(
        "XXXX",
        financials=_clean(interest_bearing_debt=500.0),
        in_official_index=True,
    )

    assert result.status is ShariaStatus.BORDERLINE
    assert not result.tradeable
    assert any("stale" in r for r in result.reasons)


# --- purification -------------------------------------------------------------


def test_purification_is_proportional_to_impure_revenue():
    financials = _clean(non_compliant_revenue=25.0)  # 5% of 500

    assert purification_due(financials, income_received=1000.0) == 50.0


def test_nothing_to_purify_when_revenue_is_clean():
    assert purification_due(_clean(), income_received=1000.0) == 0.0


def test_no_purification_owed_on_zero_income():
    assert purification_due(_clean(non_compliant_revenue=25.0), income_received=0.0) == 0.0
