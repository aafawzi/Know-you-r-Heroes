"""Sharia compliance screening — a hard constraint, not a score.

Nothing in this system may emit a BUY for a company that is not
COMPLIANT (or COMPLIANT_WITH_PURIFICATION where the user has explicitly
opted in). Everything here is built so the *safe* answer is the default:
absent or incomplete information yields UNKNOWN, and UNKNOWN never trades.

Two independent evidence paths, deliberately kept separate:

1. **Official EGX 33 Shariah index membership.** Authoritative - screened
   by EGX's own Shariah board to AAOIFI-style rules. Free and verifiable.
   Its weakness is that it is point-in-time: we can state today's status
   confidently but cannot reconstruct 2022's, so every assessment carries
   the snapshot date it rests on.
2. **Independent AAOIFI-style ratio screen.** Needs balance-sheet figures
   which no free API supplies for EGX. At ~33 companies these are entered
   by hand from published financials, each tagged with its period and
   source. Slower, but auditable - and for a religious constraint that is
   the right trade.

Where the two disagree, the disagreement is surfaced rather than silently
resolved: a stock in the official index whose ratios have drifted out of
bounds becomes BORDERLINE and is flagged for review, because a stale
index snapshot is exactly the failure mode continuous monitoring exists
to catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

# AAOIFI-style thresholds, as applied by the EGX 33 Shariah index:
# interest-bearing debt, and cash plus interest-bearing securities, each
# below a third of market capitalisation, and impure revenue under 5%.
MAX_DEBT_RATIO = 0.33
MAX_CASH_SECURITIES_RATIO = 0.33
MAX_RECEIVABLES_RATIO = 0.33
MAX_NON_COMPLIANT_REVENUE_RATIO = 0.05

# A company sitting just inside a limit can cross it on the next filing.
# Within this fraction of a threshold, report BORDERLINE rather than a
# clean pass - the point is to prompt a look, not to fail the stock.
BORDERLINE_MARGIN = 0.90

# Core business activities that are prohibited outright. No ratio can
# rescue these, so they short-circuit the whole screen.
PROHIBITED_ACTIVITIES = frozenset(
    {
        "conventional_banking",
        "conventional_insurance",
        "interest_based_finance",
        "brokerage_interest",
        "alcohol",
        "tobacco",
        "gambling",
        "pork",
        "adult_entertainment",
        "weapons_controversial",
    }
)


class ShariaStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    COMPLIANT_WITH_PURIFICATION = "COMPLIANT_WITH_PURIFICATION"
    BORDERLINE = "BORDERLINE"
    NON_COMPLIANT = "NON_COMPLIANT"
    UNKNOWN = "UNKNOWN"


#: Statuses that may ever produce a BUY. COMPLIANT_WITH_PURIFICATION is
#: deliberately excluded here and must be opted into per-ticker in config,
#: because it obliges the holder to donate the impure portion.
TRADEABLE_BY_DEFAULT = frozenset({ShariaStatus.COMPLIANT})


@dataclass(frozen=True)
class Financials:
    """Figures needed for the ratio screen, with provenance attached.

    `period` and `source` are mandatory rather than optional: an
    unattributable compliance claim is not worth making.
    """

    market_cap: float
    interest_bearing_debt: float
    cash_and_interest_securities: float
    receivables: float
    total_revenue: float
    non_compliant_revenue: float
    period: str
    source: str


@dataclass
class Assessment:
    symbol: str
    status: ShariaStatus
    reasons: list[str] = field(default_factory=list)
    ratios: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    assessed_on: date | None = None

    @property
    def tradeable(self) -> bool:
        return self.status in TRADEABLE_BY_DEFAULT

    def summary(self) -> str:
        basis = "; ".join(self.evidence) if self.evidence else "no evidence recorded"
        return f"{self.symbol}: {self.status.value} ({basis})"


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator or denominator <= 0:
        return None
    return numerator / denominator


def screen(
    symbol: str,
    *,
    activities: set[str] | None = None,
    financials: Financials | None = None,
    in_official_index: bool | None = None,
    index_snapshot_date: str | None = None,
    assessed_on: date | None = None,
) -> Assessment:
    """Classify one company. Missing information yields UNKNOWN, never a pass.

    `in_official_index=None` means "we have not checked", which is
    materially different from False ("checked, and it is absent") - the
    first is ignorance, the second is evidence.
    """
    assessment = Assessment(symbol=symbol, status=ShariaStatus.UNKNOWN, assessed_on=assessed_on or date.today())

    # 1. Prohibited business activity overrides everything else.
    banned = sorted((activities or set()) & PROHIBITED_ACTIVITIES)
    if banned:
        assessment.status = ShariaStatus.NON_COMPLIANT
        assessment.reasons.append(f"prohibited core activity: {', '.join(banned)}")
        assessment.evidence.append("business-activity screen")
        return assessment

    # 2. Ratio screen, when the figures exist.
    ratio_status: ShariaStatus | None = None
    if financials is not None:
        ratio_status = _screen_ratios(financials, assessment)

    # 3. Official index membership.
    if in_official_index is True:
        assessment.evidence.append(
            f"EGX 33 Shariah constituent (snapshot {index_snapshot_date or 'undated'})"
        )
    elif in_official_index is False:
        assessment.evidence.append("absent from EGX 33 Shariah constituents")

    # 4. Combine. The ratio screen is the more specific evidence, so it
    #    leads; index membership can confirm it or, on disagreement,
    #    downgrade to BORDERLINE for review.
    if ratio_status is not None:
        assessment.status = ratio_status
        if in_official_index is True and ratio_status is ShariaStatus.NON_COMPLIANT:
            # Do not quietly trust the older of two sources. Flag it.
            assessment.status = ShariaStatus.BORDERLINE
            assessment.reasons.append(
                "official index lists this company but current ratios breach AAOIFI limits "
                "- index snapshot may be stale; manual review required"
            )
        return assessment

    if in_official_index is True:
        assessment.status = ShariaStatus.COMPLIANT
        assessment.reasons.append(
            "screened by the EGX Shariah supervisory board; no independent ratio check available"
        )
        return assessment

    assessment.reasons.append(
        "no financials and no confirmed index membership - compliance cannot be established"
    )
    return assessment


def _screen_ratios(f: Financials, assessment: Assessment) -> ShariaStatus:
    """Apply AAOIFI-style ratios, recording every computed value."""
    assessment.evidence.append(f"AAOIFI ratio screen on {f.period} ({f.source})")

    checks = (
        ("debt_to_market_cap", _ratio(f.interest_bearing_debt, f.market_cap), MAX_DEBT_RATIO),
        (
            "cash_securities_to_market_cap",
            _ratio(f.cash_and_interest_securities, f.market_cap),
            MAX_CASH_SECURITIES_RATIO,
        ),
        ("receivables_to_market_cap", _ratio(f.receivables, f.market_cap), MAX_RECEIVABLES_RATIO),
        (
            "non_compliant_revenue_share",
            _ratio(f.non_compliant_revenue, f.total_revenue),
            MAX_NON_COMPLIANT_REVENUE_RATIO,
        ),
    )

    breached: list[str] = []
    near_limit: list[str] = []
    missing: list[str] = []

    for label, value, limit in checks:
        if value is None:
            missing.append(label)
            continue
        assessment.ratios[label] = value
        if value > limit:
            breached.append(f"{label}={value:.1%} > {limit:.0%}")
        elif value >= limit * BORDERLINE_MARGIN:
            near_limit.append(f"{label}={value:.1%} (limit {limit:.0%})")

    if missing:
        # A partial screen is not a screen. Refuse to conclude.
        assessment.reasons.append(f"incomplete figures: {', '.join(missing)}")
        return ShariaStatus.UNKNOWN

    if breached:
        assessment.reasons.append("AAOIFI limits breached: " + "; ".join(breached))
        return ShariaStatus.NON_COMPLIANT

    impure = assessment.ratios["non_compliant_revenue_share"]
    if near_limit:
        assessment.reasons.append("within margin of an AAOIFI limit: " + "; ".join(near_limit))
        return ShariaStatus.BORDERLINE

    if impure > 0:
        assessment.reasons.append(
            f"{impure:.2%} of revenue is non-compliant - permissible but that share must be purified"
        )
        return ShariaStatus.COMPLIANT_WITH_PURIFICATION

    assessment.reasons.append("passes all AAOIFI ratio limits with no impure revenue")
    return ShariaStatus.COMPLIANT


def purification_due(financials: Financials, income_received: float) -> float:
    """EGP to donate on `income_received` (dividends, or gains if you purify those).

    Purification is the holder's obligation, not the screen's: the point of
    returning a number is that it can actually be acted on.
    """
    share = _ratio(financials.non_compliant_revenue, financials.total_revenue)
    if share is None or income_received <= 0:
        return 0.0
    return income_received * share
