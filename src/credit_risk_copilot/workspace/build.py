"""Turning stored assessments into the objects the workspace renders.

Two sources, both real, neither invented:

- **The audit store** (Phase 13) holds the assessments, their evidence, their
  drafts and every analyst decision. It is the spine: identity, as-of date,
  contradictions, verbatim quotes, model attribution and caveats all come from
  here, and every figure traces to an `EV-` item with a filing behind it.
- **The Phase 8 point-in-time panel** supplies multi-year ratio history. An
  assessment describes one as-of date; a trend chart needs the years before
  it, and the panel is the only place those exist as *point-in-time* values --
  each row was computed from filings available at that date, so a chart drawn
  from it is not a restated back-fill.

Everything else the screen wants and the system does not have -- EBITDA, peer
benchmarks, sector metadata, quarterly periods, earnings-call sentiment -- is
absent here rather than approximated, and `workspace/README` in the Method
page says so to the analyst directly.

## Revenue and total assets are recovered, not invented

The panel stores `log_revenue` and `log_total_assets`, natural logs of real
reported figures, so `exp()` returns the reported figure exactly. That is a
transform of a measured value, not an estimate, and the UI labels it as
derived so nobody mistakes it for a tagged line item.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.assessment import reads as layer_reads
from credit_risk_copilot.assessment.models import (
    Assessment,
    Concern,
    EvidenceItem,
    EvidenceKind,
    LayerId,
)
from credit_risk_copilot.health.direction import RATIO_DIRECTIONS
from credit_risk_copilot.health.models import RatioDirection
from credit_risk_copilot.ratios.registry import RATIOS_BY_ID
from credit_risk_copilot.review.models import AssessmentHistory, AssessmentState
from credit_risk_copilot.review.store import ReviewStore
from credit_risk_copilot.workspace.models import (
    ATTENTION_ALL_ELEVATED,
    ATTENTION_COVERAGE,
    ATTENTION_DISAGREEMENT,
    ATTENTION_DRAFT_REJECTED,
    ATTENTION_ORDER,
    ATTENTION_SEVERE_DISCLOSURE,
    ATTENTION_UNREVIEWED,
    CompanyCard,
    CompanyWorkspace,
    CoverageGap,
    DriverBar,
    LayerRead,
    MetricPoint,
    NarrativeItem,
    RatioSeries,
)

PANEL_PATH = Path("data/processed/phase8/observations_primary.csv")
DEFAULT_DB = Path("data/processed/phase13/workspace.db")

#: Attribution groups that describe the filing rather than the company.
FILING_ARTEFACT_GROUPS = frozenset({"missingness", "data_quality"})

#: Phase 10 codes whose measured specificity is HIGH -- the ones that put a
#: company on the desk on their own.
SEVERE_CODES = frozenset(
    {
        "going_concern_doubt",
        "bankruptcy_contemplated",
        "debt_default_or_acceleration",
        "debt_restructuring",
        "covenant_waiver_or_amendment",
        "delisting_notice",
    }
)


# ---------------------------------------------------------------------------
# The three reads


def _health_read(assessment: Assessment) -> LayerRead:
    dimensions = assessment.of_kind(EvidenceKind.DIMENSION_STATUS)
    if not dimensions:
        return LayerRead(
            layer=LayerId.FINANCIAL_HEALTH,
            concern=Concern.UNKNOWN,
            headline="Not run",
            detail=_absence(assessment, LayerId.FINANCIAL_HEALTH),
            available=False,
            unavailable_reason=_absence(assessment, LayerId.FINANCIAL_HEALTH),
        )
    deteriorating = [d for d in dimensions if d.detail.get("status") == "deteriorating"]
    conclusive = [d for d in dimensions if d.detail.get("status") != "insufficient_data"]
    signals = assessment.of_kind(EvidenceKind.HEALTH_SIGNAL)
    concern = layer_reads.read(assessment.evidence, LayerId.FINANCIAL_HEALTH)

    if deteriorating:
        headline = f"{len(deteriorating)} of {len(dimensions)} dimensions deteriorating"
        detail = ", ".join(sorted(d.dimension or "" for d in deteriorating))
    elif conclusive:
        headline = "No dimension deteriorating"
        detail = f"{len(conclusive)} of {len(dimensions)} dimensions reached a conclusion"
    else:
        headline = "No conclusive trend"
        detail = "Too little gap-free history to read a direction"
    if signals:
        detail += f" · {len(signals)} early-warning signal(s)"
    return LayerRead(
        layer=LayerId.FINANCIAL_HEALTH,
        concern=concern,
        headline=headline,
        detail=detail,
        evidence_ids=tuple(d.evidence_id for d in (deteriorating or dimensions))
        + tuple(s.evidence_id for s in signals),
    )


def _model_read(assessment: Assessment) -> LayerRead:
    scores = assessment.of_kind(EvidenceKind.MODEL_SCORE)
    if not scores:
        return LayerRead(
            layer=LayerId.PREDICTIVE_MODEL,
            concern=Concern.UNKNOWN,
            headline="Not scored",
            detail=_absence(assessment, LayerId.PREDICTIVE_MODEL),
            available=False,
            unavailable_reason=_absence(assessment, LayerId.PREDICTIVE_MODEL),
        )
    score = scores[0]
    percentile = score.detail.get("score_percentile")
    concern = layer_reads.read(assessment.evidence, LayerId.PREDICTIVE_MODEL)
    if isinstance(percentile, (int, float)):
        headline = f"{percentile:.0f}th percentile"
        detail = "of companies scored in the same year — a ranking position, not a probability"
    else:
        headline = "No ranking position"
        detail = "Scored without a comparison population"
    caveats = assessment.of_kind(EvidenceKind.MODEL_CAVEAT)
    return LayerRead(
        layer=LayerId.PREDICTIVE_MODEL,
        concern=concern,
        headline=headline,
        detail=detail,
        evidence_ids=(score.evidence_id,) + tuple(c.evidence_id for c in caveats),
    )


def _narrative_read(assessment: Assessment) -> LayerRead:
    signals = assessment.of_kind(EvidenceKind.NARRATIVE_SIGNAL)
    gaps = assessment.of_kind(EvidenceKind.NARRATIVE_COVERAGE)
    if not signals and not gaps:
        return LayerRead(
            layer=LayerId.NARRATIVE,
            concern=Concern.UNKNOWN,
            headline="Not read",
            detail=_absence(assessment, LayerId.NARRATIVE),
            available=False,
            unavailable_reason=_absence(assessment, LayerId.NARRATIVE),
        )
    asserted = [s for s in signals if s.detail.get("assertion") == "asserted"]
    severe = [s for s in asserted if str(s.detail.get("code")) in SEVERE_CODES]
    concern = layer_reads.read(assessment.evidence, LayerId.NARRATIVE)

    if severe:
        headline = _humanise(str(severe[0].detail.get("code")))
        if len(severe) > 1:
            headline += f" +{len(severe) - 1} more"
        detail = "Stated by the filer about itself, with the sentence attached"
    elif asserted:
        headline = f"{len(asserted)} disclosure(s) stated"
        detail = "None of them high-specificity"
    else:
        headline = "Nothing stated"
        detail = "Risk-factor language present but conditional, not asserted"
    if gaps:
        detail += f" · {len(gaps)} section(s) not located"
    return LayerRead(
        layer=LayerId.NARRATIVE,
        concern=concern,
        headline=headline,
        detail=detail,
        evidence_ids=tuple(s.evidence_id for s in (severe or asserted or signals))
        + tuple(g.evidence_id for g in gaps),
    )


def _absence(assessment: Assessment, layer: LayerId) -> str:
    for absence in assessment.layers_absent:
        if absence.layer is layer:
            return absence.reason
    return "This layer produced no evidence for this filing."


def _humanise(code: str) -> str:
    return code.replace("_", " ").capitalize()


def three_reads(assessment: Assessment) -> tuple[LayerRead, ...]:
    """The centrepiece: three independent methods, side by side."""
    return (_health_read(assessment), _model_read(assessment), _narrative_read(assessment))


# ---------------------------------------------------------------------------
# Attention reasons


def attention_reasons(assessment: Assessment, history: AssessmentHistory) -> tuple[str, ...]:
    """Why this company is on the desk, as named reasons rather than a score.

    Each reason is a checkable fact. They are returned in a fixed order for
    stable rendering, and they are deliberately *not* weighted against each
    other -- an analyst reading "layers disagree" and "not yet reviewed"
    should decide which matters today, not be told.
    """
    found: set[str] = set()
    if assessment.contradictions:
        found.add(ATTENTION_DISAGREEMENT)
    if len([r for r in three_reads(assessment) if r.concern is Concern.ELEVATED]) == 3:
        found.add(ATTENTION_ALL_ELEVATED)
    if history.effective_review is None:
        found.add(ATTENTION_UNREVIEWED)
    if history.draft_accepted is False:
        found.add(ATTENTION_DRAFT_REJECTED)
    if assessment.of_kind(EvidenceKind.NARRATIVE_COVERAGE):
        found.add(ATTENTION_COVERAGE)
    if any(
        item.detail.get("assertion") == "asserted" and str(item.detail.get("code")) in SEVERE_CODES
        for item in assessment.of_kind(EvidenceKind.NARRATIVE_SIGNAL)
    ):
        found.add(ATTENTION_SEVERE_DISCLOSURE)
    return tuple(reason for reason in ATTENTION_ORDER if reason in found)


def build_card(assessment: Assessment, history: AssessmentHistory) -> CompanyCard:
    return CompanyCard(
        cik=assessment.cik,
        company=assessment.company,
        as_of=assessment.as_of,
        period_label=assessment.period_label,
        assessment_id=history.assessment_id,
        state=history.state,
        watch_status=history.watch_status,
        reads=three_reads(assessment),
        n_contradictions=len(assessment.contradictions),
        n_corroborations=len(assessment.corroborations),
        n_evidence=len(assessment.evidence),
        draft_id=history.draft_id,
        draft_accepted=history.draft_accepted,
        attention=attention_reasons(assessment, history),
    )


# ---------------------------------------------------------------------------
# Model attribution and narrative


def drivers(assessment: Assessment, *, limit: int = 8) -> tuple[DriverBar, ...]:
    """Attribution by dimension, largest share first.

    Filing-artefact groups are kept in the list rather than filtered out. A
    model reacting to an absent tag is not a finding about leverage, and
    hiding that would make the chart read as though every driver were
    financial -- which is the specific over-reading Phase 9 measured.
    """
    bars = [
        DriverBar(
            group=str(item.detail.get("group")),
            contribution=float(item.detail.get("contribution") or 0.0),
            share=float(item.detail.get("share_of_absolute") or 0.0),
            feature_count=int(item.detail.get("feature_count") or 0),
            raises_risk=bool(item.detail.get("raises_risk")),
            evidence_id=item.evidence_id,
            is_filing_artefact=str(item.detail.get("group")) in FILING_ARTEFACT_GROUPS,
        )
        for item in assessment.of_kind(EvidenceKind.MODEL_DRIVER)
    ]
    return tuple(sorted(bars, key=lambda b: -b.share)[:limit])


def caveats(assessment: Assessment) -> tuple[tuple[str, str], ...]:
    """Structured reasons the model output must not be read at face value."""
    return tuple(
        (str(item.detail.get("code")), item.summary.split(": ", 1)[-1])
        for item in assessment.of_kind(EvidenceKind.MODEL_CAVEAT)
    )


def narrative_items(assessment: Assessment) -> tuple[NarrativeItem, ...]:
    """Disclosures, asserted ones first, each with its sentence."""
    items = [
        NarrativeItem(
            code=str(item.detail.get("code")),
            label=_humanise(str(item.detail.get("code"))),
            assertion=str(item.detail.get("assertion")),
            specificity=str(item.detail.get("specificity")),
            section=item.detail.get("section_id") and str(item.detail.get("section_id")),
            occurrences=int(item.detail.get("occurrences") or 1),
            quote=item.quote,
            evidence_id=item.evidence_id,
            accession=item.accession,
        )
        for item in assessment.of_kind(EvidenceKind.NARRATIVE_SIGNAL)
    ]
    severity = {"high": 0, "moderate": 1, "low": 2}
    return tuple(
        sorted(
            items,
            key=lambda i: (
                0 if i.is_asserted else 1,
                severity.get(i.specificity, 3),
                i.code,
            ),
        )
    )


def coverage_gaps(assessment: Assessment) -> tuple[CoverageGap, ...]:
    return tuple(
        CoverageGap(
            section=str(item.detail.get("section_id")),
            evidence_id=item.evidence_id,
            note=item.summary,
        )
        for item in assessment.of_kind(EvidenceKind.NARRATIVE_COVERAGE)
    )


# ---------------------------------------------------------------------------
# Ratio history from the point-in-time panel


def _panel_rows(panel: pd.DataFrame, cik: int, as_of: date) -> pd.DataFrame:
    """Every observation for a company at or before the as-of date.

    The filter is the same point-in-time rule the rest of the project uses:
    a chart on an assessment dated 2015-03-02 may not contain a value that was
    only knowable later, or the replay is decoration.
    """
    # An absent panel is a DataFrame with no columns at all, not just no rows,
    # so the column check has to come first -- `load_panel` promises the
    # workspace degrades to "no trend charts" rather than crashing, and
    # indexing a missing column would break that promise loudly.
    if panel.empty or "cik" not in panel.columns:
        return pd.DataFrame()
    rows = panel[panel["cik"] == cik].copy()
    if rows.empty:
        return rows
    rows["prediction_date"] = pd.to_datetime(rows["prediction_date"]).dt.date
    rows = rows[rows["prediction_date"] <= as_of]
    return rows.sort_values("prediction_date")


def ratio_series(
    panel: pd.DataFrame, assessment: Assessment, *, cik: int, as_of: date
) -> tuple[RatioSeries, ...]:
    rows = _panel_rows(panel, cik, as_of)
    directions = {
        item.detail.get("ratio_id") or _ratio_of(item): item.detail.get("economic_direction")
        for item in assessment.of_kind(EvidenceKind.RATIO_TREND)
    }
    out: list[RatioSeries] = []
    for ratio_id, definition in sorted(RATIOS_BY_ID.items()):
        column = f"ratio_{ratio_id}"
        if rows.empty or column not in rows.columns:
            points: tuple[MetricPoint, ...] = ()
        else:
            points = tuple(
                MetricPoint(
                    period=str(row["fiscal_period_label"]),
                    value=None if pd.isna(row[column]) else float(row[column]),
                )
                for _, row in rows.iterrows()
            )
        out.append(
            RatioSeries(
                ratio_id=ratio_id,
                name=definition.name,
                category=definition.category,
                formula=definition.formula_display,
                points=points,
                economic_direction=directions.get(ratio_id),
                higher_is_stronger=RATIO_DIRECTIONS.get(ratio_id)
                is RatioDirection.HIGHER_IS_STRONGER,
            )
        )
    return tuple(out)


def _ratio_of(item: EvidenceItem) -> str:
    return item.identity_key.rsplit(":", 1)[-1]


#: Panel columns that are worth showing as scale context, with how to read
#: them. `log_*` columns are exponentiated back to the reported figure.
SCALE_FIELDS: dict[str, tuple[str, str]] = {
    "log_revenue": ("Revenue", "currency_from_log"),
    "log_total_assets": ("Total assets", "currency_from_log"),
    "ebit_to_assets": ("EBIT / assets", "ratio"),
    "fcf_to_assets": ("Free cash flow / assets", "ratio"),
    "cash_to_assets": ("Cash / assets", "ratio"),
    "working_capital_to_assets": ("Working capital / assets", "ratio"),
}


def scale_history(
    panel: pd.DataFrame, *, cik: int, as_of: date
) -> tuple[dict[str, MetricPoint], dict[str, tuple[MetricPoint, ...]]]:
    """Size and cash-generation context, latest value plus history."""
    rows = _panel_rows(panel, cik, as_of)
    latest: dict[str, MetricPoint] = {}
    history: dict[str, tuple[MetricPoint, ...]] = {}
    if rows.empty:
        return latest, history

    for column, (_, kind) in SCALE_FIELDS.items():
        if column not in rows.columns:
            continue
        points: list[MetricPoint] = []
        for _, row in rows.iterrows():
            raw = row[column]
            if pd.isna(raw):
                points.append(MetricPoint(period=str(row["fiscal_period_label"]), value=None))
                continue
            value = math.exp(float(raw)) if kind == "currency_from_log" else float(raw)
            points.append(MetricPoint(period=str(row["fiscal_period_label"]), value=value))
        history[column] = tuple(points)
        observed = [p for p in points if p.value is not None]
        if observed:
            latest[column] = observed[-1]
    return latest, history


# ---------------------------------------------------------------------------
# Assembly


def load_panel(path: Path = PANEL_PATH) -> pd.DataFrame:
    """The Phase 8 point-in-time panel, or an empty frame if it is absent.

    Absence is survivable: without the panel the workspace loses its trend
    charts and keeps everything the audit store holds, which is the majority
    of the page. The Method page states which half is missing rather than the
    charts silently rendering empty.
    """
    if not path.exists():
        return pd.DataFrame()
    keep = ["cik", "company", "fiscal_period_label", "prediction_date"]
    frame = pd.read_csv(path)
    columns = [c for c in frame.columns if c.startswith("ratio_") or c in SCALE_FIELDS]
    return frame[keep + columns]


def build_workspace(
    store: ReviewStore, history: AssessmentHistory, panel: pd.DataFrame
) -> CompanyWorkspace:
    """Everything the company page renders, for one assessment version."""
    assessment = store.load_assessment(history.assessment_id)
    scores = assessment.of_kind(EvidenceKind.MODEL_SCORE)
    percentile: float | None = None
    model_name: str | None = None
    if scores:
        raw = scores[0].detail.get("score_percentile")
        percentile = float(raw) if isinstance(raw, (int, float)) else None
        model_name = scores[0].detail.get("model_name") and str(scores[0].detail["model_name"])

    latest_scale, scale_hist = scale_history(panel, cik=assessment.cik, as_of=assessment.as_of)
    return CompanyWorkspace(
        card=build_card(assessment, history),
        evidence=assessment.evidence,
        contradictions=assessment.contradictions,
        corroborations=assessment.corroborations,
        drivers=drivers(assessment),
        caveats=caveats(assessment),
        narrative=narrative_items(assessment),
        coverage_gaps=coverage_gaps(assessment),
        ratios=ratio_series(panel, assessment, cik=assessment.cik, as_of=assessment.as_of),
        scale=latest_scale,
        scale_history=scale_hist,
        pipeline_versions=history.pipeline_versions,
        score_percentile=percentile,
        model_name=model_name,
    )


def coverage(store: ReviewStore, panel: pd.DataFrame) -> tuple[CompanyCard, ...]:
    """Every company's current assessment, as cards for the desk."""
    cards: list[CompanyCard] = []
    for history in store.watchlist():
        try:
            assessment = store.load_assessment(history.assessment_id)
        except KeyError:  # pragma: no cover - a store missing its own row
            continue
        cards.append(build_card(assessment, history))
    return tuple(cards)


def group_by_attention(cards: tuple[CompanyCard, ...]) -> dict[str, list[CompanyCard]]:
    """The desk's structure: one bucket per named reason.

    A company appears under every reason that applies to it, which is the
    point -- the analyst sees *why* it surfaced rather than a position in a
    queue whose ordering nobody can explain.
    """
    grouped: dict[str, list[CompanyCard]] = {reason: [] for reason in ATTENTION_ORDER}
    for card in cards:
        for reason in card.attention:
            grouped[reason].append(card)
    for bucket in grouped.values():
        bucket.sort(key=lambda c: c.company)
    return {reason: bucket for reason, bucket in grouped.items() if bucket}


def state_label(state: AssessmentState) -> str:
    return {
        AssessmentState.DRAFT: "Awaiting review",
        AssessmentState.APPROVED: "Approved",
        AssessmentState.MODIFIED: "Modified by analyst",
        AssessmentState.REJECTED: "Rejected",
        AssessmentState.SUPERSEDED: "Superseded",
    }[state]


def format_currency(value: float | None) -> str:
    """Compact currency for scanning, with the unit always visible."""
    if value is None:
        return "—"
    for threshold, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= threshold:
            return f"${value / threshold:,.2f}{suffix}"
    return f"${value:,.0f}"


def format_ratio(value: float | None, *, places: int = 2) -> str:
    return "—" if value is None else f"{value:,.{places}f}"


def format_percent(value: float | None, *, places: int = 1) -> str:
    return "—" if value is None else f"{value * 100:,.{places}f}%"


def describe(item: EvidenceItem) -> dict[str, Any]:
    """An evidence item flattened for a detail panel."""
    return {
        "Evidence ID": item.evidence_id,
        "Layer": item.layer.value,
        "Kind": item.kind.value,
        "Dimension": item.dimension or "—",
        "Period": item.period_label or "—",
        "Filing": item.accession or "—",
        "Filed": item.filed.isoformat() if item.filed else "—",
    }
