"""The workspace view models: what the screen is allowed to say.

These test the decisions, not the pixels. The UI renders whatever these
objects contain, so "there is no combined score", "an absent layer is not a
quiet one" and "a company is on the desk for a named reason" are properties
that have to hold here or they do not hold at all.
"""

from __future__ import annotations

from dataclasses import fields

import pandas as pd
import pytest

from credit_risk_copilot.assessment.models import Concern, LayerId
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode, Specificity
from credit_risk_copilot.review.models import AssessmentHistory, AssessmentState
from credit_risk_copilot.workspace import (
    ATTENTION_EXPLANATIONS,
    ATTENTION_ORDER,
    CompanyCard,
    CompanyWorkspace,
    attention_reasons,
    build_card,
    drivers,
    format_currency,
    group_by_attention,
    narrative_items,
    ratio_series,
    scale_history,
    three_reads,
)
from credit_risk_copilot.workspace.models import (
    ATTENTION_ALL_ELEVATED,
    ATTENTION_DISAGREEMENT,
    ATTENTION_SEVERE_DISCLOSURE,
    ATTENTION_UNREVIEWED,
)

from ._assessment_helpers import narrative_signal
from .test_synthesis_validator import build_assessment


def history_for(assessment, *, reviews=(), draft_accepted=None) -> AssessmentHistory:
    return AssessmentHistory(
        assessment_id="AS-test",
        cik=assessment.cik,
        company=assessment.company,
        as_of=assessment.as_of.isoformat(),
        period_label=assessment.period_label,
        state=AssessmentState.DRAFT,
        is_current=True,
        draft_id="DR-test" if draft_accepted is not None else None,
        draft_model="gemini-3.6-flash",
        draft_accepted=draft_accepted,
        reviews=tuple(reviews),
    )


# --------------------------------------------------------------------------
# The centrepiece


def test_there_is_no_combined_score_anywhere_in_the_view_models():
    """The single most important property of this UI.

    Four decisions refused a combined risk number. A field called `score`,
    `risk`, `rating` or `confidence` on the object the page renders would be
    that number arriving at last, disguised as a widget -- and it would be the
    one element on screen with no filing behind it.
    """
    names = {f.name for f in fields(CompanyWorkspace)} | {f.name for f in fields(CompanyCard)}
    forbidden = {"score", "risk_score", "overall_score", "confidence", "rating", "severity"}
    assert names & forbidden == set()
    # The only score-shaped field is explicitly a ranking position.
    assert "score_percentile" in {f.name for f in fields(CompanyWorkspace)}


def test_the_three_reads_are_three_independent_layers():
    reads = three_reads(build_assessment())
    assert [r.layer for r in reads] == [
        LayerId.FINANCIAL_HEALTH,
        LayerId.PREDICTIVE_MODEL,
        LayerId.NARRATIVE,
    ]
    # Each read states its own method, so an analyst comparing verdicts knows
    # one is arithmetic, one is a fitted model and one is a regex over English.
    assert all(r.method for r in reads)
    assert all(r.headline for r in reads)


def test_a_layer_that_did_not_run_is_not_a_quiet_layer():
    """`available=False` is kept apart from `concern=QUIET`: "we looked and
    found nothing" and "we did not look" are different answers."""
    assessment = build_assessment(with_model=False)
    model = next(r for r in three_reads(assessment) if r.layer is LayerId.PREDICTIVE_MODEL)
    assert model.available is False
    assert model.concern is Concern.UNKNOWN
    assert model.unavailable_reason


def test_the_model_read_never_calls_itself_a_probability():
    read = next(r for r in three_reads(build_assessment()) if r.layer is LayerId.PREDICTIVE_MODEL)
    assert "percentile" in read.headline
    assert "not a probability" in read.detail
    assert "%" not in read.headline or "percentile" in read.headline


# --------------------------------------------------------------------------
# The desk


def test_a_company_reaches_the_desk_for_named_reasons():
    assessment = build_assessment()
    reasons = attention_reasons(assessment, history_for(assessment))
    assert ATTENTION_UNREVIEWED in reasons
    assert ATTENTION_SEVERE_DISCLOSURE in reasons
    # Every reason is explainable to the analyst.
    assert all(reason in ATTENTION_EXPLANATIONS for reason in reasons)


def test_reasons_come_back_in_a_fixed_order_and_are_not_ranked():
    assessment = build_assessment()
    reasons = attention_reasons(assessment, history_for(assessment))
    assert list(reasons) == [r for r in ATTENTION_ORDER if r in reasons]


def test_a_reviewed_assessment_leaves_the_unreviewed_bucket():
    from datetime import UTC, datetime

    from credit_risk_copilot.review.models import (
        AnalystReview,
        CreditWatchStatus,
        ReviewDecision,
    )

    assessment = build_assessment()
    review = AnalystReview(
        review_id="RV-1",
        draft_id="DR-test",
        assessment_id="AS-test",
        analyst="k",
        decision=ReviewDecision.APPROVE,
        watch_status=CreditWatchStatus.MONITOR,
        recorded_at=datetime.now(UTC),
    )
    reasons = attention_reasons(assessment, history_for(assessment, reviews=[review]))
    assert ATTENTION_UNREVIEWED not in reasons


def test_a_failed_draft_puts_a_company_on_the_desk():
    assessment = build_assessment()
    reasons = attention_reasons(assessment, history_for(assessment, draft_accepted=False))
    assert "Draft failed grounding" in reasons


def test_the_desk_groups_by_reason_rather_than_ranking():
    assessment = build_assessment()
    card = build_card(assessment, history_for(assessment))
    buckets = group_by_attention((card,))
    # The same company legitimately appears under several reasons -- the
    # analyst sees why it surfaced rather than a position in a queue.
    assert len(buckets) > 1
    assert all(card in bucket for bucket in buckets.values())


def test_all_three_layers_elevated_requires_all_three():
    assessment = build_assessment()
    card = build_card(assessment, history_for(assessment))
    elevated = card.elevated_layers
    if len(elevated) == 3:
        assert ATTENTION_ALL_ELEVATED in card.attention
    else:
        assert ATTENTION_ALL_ELEVATED not in card.attention


def test_contradictions_put_a_company_on_the_desk():
    assessment = build_assessment()
    assert assessment.contradictions
    assert ATTENTION_DISAGREEMENT in attention_reasons(assessment, history_for(assessment))


# --------------------------------------------------------------------------
# Attribution and narrative


def test_filing_artefact_attribution_is_labelled_not_hidden():
    """A model reacting to an absent tag is not a finding about leverage, and
    a chart that filtered it out would read as though every driver were
    financial."""
    from credit_risk_copilot.workspace.build import FILING_ARTEFACT_GROUPS

    from ._assessment_helpers import explanation

    assessment = build_assessment()
    bars = drivers(assessment)
    for bar in bars:
        assert bar.is_filing_artefact == (bar.group in FILING_ARTEFACT_GROUPS)
    assert explanation is not None  # helper import is intentional


def test_drivers_are_ordered_by_share_of_attribution():
    shares = [bar.share for bar in drivers(build_assessment())]
    assert shares == sorted(shares, reverse=True)


def test_asserted_disclosures_sort_above_conditional_ones():
    from credit_risk_copilot.assessment.evidence import narrative_evidence
    from credit_risk_copilot.assessment.models import Assessment

    from ._assessment_helpers import narrative_report

    report = narrative_report(
        signals=(
            narrative_signal(
                RiskSignalCode.ASSET_IMPAIRMENT,
                Assertion.ASSERTED,
                specificity=Specificity.LOW,
                text="An impairment was recorded.",
            ),
            narrative_signal(
                RiskSignalCode.GOING_CONCERN_DOUBT,
                Assertion.ASSERTED,
                specificity=Specificity.HIGH,
                char_start=900,
            ),
        )
    )
    assessment = Assessment(
        cik=1,
        company="TEST CO",
        as_of=report_date(report),
        evidence=narrative_evidence(report),
    )
    items = narrative_items(assessment)
    # High specificity first: a going-concern statement outranks an impairment.
    assert items[0].code == "going_concern_doubt"
    assert all(item.quote for item in items)


def report_date(report):
    from datetime import date

    return date.fromisoformat(str(report.filed))


# --------------------------------------------------------------------------
# Point-in-time series


def test_ratio_history_never_includes_a_period_after_the_as_of_date():
    """A trend chart on a replayed assessment must not contain a value that
    was only knowable later, or the replay is decoration."""
    assessment = build_assessment()
    panel = pd.DataFrame(
        {
            "cik": [assessment.cik] * 3,
            "company": [assessment.company] * 3,
            "fiscal_period_label": ["FY2013", "FY2014", "FY2015"],
            "prediction_date": ["2014-03-01", "2015-03-01", "2016-03-01"],
            "ratio_current_ratio": [1.5, 1.2, 0.4],
            "log_revenue": [20.0, 20.1, 19.5],
        }
    )
    series = ratio_series(panel, assessment, cik=assessment.cik, as_of=assessment.as_of)
    current = next(s for s in series if s.ratio_id == "current_ratio")
    periods = [p.period for p in current.observed]
    assert "FY2015" not in periods, "a later filing leaked into the chart"
    assert periods == ["FY2013", "FY2014"]


def test_revenue_is_recovered_from_the_stored_log():
    assessment = build_assessment()
    panel = pd.DataFrame(
        {
            "cik": [assessment.cik],
            "company": [assessment.company],
            "fiscal_period_label": ["FY2014"],
            "prediction_date": ["2015-03-01"],
            "log_revenue": [20.382687782981133],
        }
    )
    latest, _ = scale_history(panel, cik=assessment.cik, as_of=assessment.as_of)
    assert latest["log_revenue"].value == pytest.approx(711_359_000, rel=1e-6)


def test_an_empty_panel_degrades_to_no_series_rather_than_zeros():
    assessment = build_assessment()
    series = ratio_series(pd.DataFrame(), assessment, cik=assessment.cik, as_of=assessment.as_of)
    assert len(series) == 13
    assert all(s.observed == () for s in series)
    latest, history = scale_history(pd.DataFrame(), cik=1, as_of=assessment.as_of)
    assert latest == {} and history == {}


def test_currency_formatting_always_shows_the_unit():
    assert format_currency(711_359_000) == "$711.36M"
    assert format_currency(1_234_000_000_000) == "$1.23T"
    assert format_currency(None) == "—"
