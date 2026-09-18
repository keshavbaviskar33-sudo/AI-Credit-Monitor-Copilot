"""Phase 11: run the combination layer over the labelled corpus and measure it.

The phase's product claim is that putting four layers side by side tells you
something none of them tells you alone. That is a claim, so it gets a number.

**The headline test is matched-budget, not "higher precision".** Any conjunction
of conditions has higher precision and lower recall than its parts, so
reporting that would be reporting arithmetic. The question an analyst actually
faces is: *given that I can look at k companies this quarter, is my list better
if I build it from agreement between layers than from the model's top k?* So
every combination is compared against the model's top-k on the same corpus at
the same k. If the combination loses, the phase reports that it loses.

**Four things are measured.**

1. *Rule incidence* -- how often each contradiction and corroboration fires, in
   pre-bankruptcy filings and in comparison filings, with the ratio between
   them. A rule that fires equally in both is carrying no information, and this
   is where that shows up.
2. *Matched-budget discrimination* -- the headline above.
3. *Integrity* -- every citation in every finding resolves to an evidence item;
   evidence IDs are identical across two independent runs; every narrative
   quote that reaches an assessment is still character-for-character what
   Phase 10 emitted (SC-03 carried across the boundary).
4. *The as-of gate actually bites* -- every assessment is re-assembled one day
   before its filing date, and the gate is required to refuse all of them.

**What this script reconstructs, and why that is honest.** The model layer is
run for real: walk-forward out-of-time on the Phase 8 panel, TreeSHAP from the
fold's own fitted estimator, exactly as Phase 9 does. The health and narrative
layers are rebuilt from the committed Phase 8 and Phase 10 outputs rather than
re-derived, because re-running them means re-fetching company facts and
re-parsing 238 filings for inputs that are already recorded. The reconstruction
is lossy in one documented way (`_health_report`), and the loss is stated in
the results rather than hidden: dimension statuses come back as
deteriorating / not-deteriorating / insufficient, so `MIXED` and `IMPROVING`
are both read as not-deteriorating. Every cross-layer rule in this phase reads
exactly that three-way distinction, so the reconstruction is faithful to what
is being measured.

    uv run python scripts/phase11_assess.py
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credit_risk_copilot.assessment import (
    AsOfGate,
    AsOfViolation,
    Assessment,
    ContradictionCode,
    CorroborationCode,
    FilingStamp,
    assemble_assessment,
)
from credit_risk_copilot.assessment.contradictions import artefact_share
from credit_risk_copilot.explain.adapters import AttributionResult
from credit_risk_copilot.explain.local import explain_observation
from credit_risk_copilot.health.models import (
    DataQuality,
    DataQualityLevel,
    DimensionHealth,
    DimensionStatus,
    EconomicDirection,
    FinancialHealthReport,
    HistoryDepth,
    RatioTrend,
    Signal,
    SignalCode,
    TrendDirection,
)
from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.contract import Observation
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.model import build_model_specs
from credit_risk_copilot.modeling.splits import assert_temporal_ordering, walk_forward_folds
from credit_risk_copilot.nlp.models import (
    Assertion,
    EvidenceQuote,
    NarrativeRiskReport,
    NarrativeRiskSignal,
    RiskSignalCode,
    SectionCoverage,
    Specificity,
)
from credit_risk_copilot.ratios.models import RatioResult, RatioStatus
from credit_risk_copilot.ratios.registry import RATIOS_BY_ID

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
PHASE10_DIR = Path("data/processed/phase10")
OUT_DIR = Path("data/processed/phase11")

#: D-034 made this the primary model. The measurement below is about the
#: combination layer, not about the model, so the model is taken as shipped.
PRIMARY_MODEL = "gradient_boosting_all"

DIMENSIONS = ("liquidity", "leverage", "profitability", "coverage", "cash_flow")
#: One representative ratio per dimension, used only to give the reconstructed
#: trends a ratio id. The rules never read it; Phase 7's real reports carry all
#: thirteen.
REPRESENTATIVE = {
    "liquidity": "current_ratio",
    "leverage": "debt_to_equity",
    "profitability": "net_profit_margin",
    "coverage": "interest_coverage",
    "cash_flow": "ocf_to_revenue",
}
SIGNAL_DIMENSION = {
    SignalCode.LIQUIDITY_DETERIORATION: "liquidity",
    SignalCode.LEVERAGE_DETERIORATION: "leverage",
    SignalCode.MARGIN_COMPRESSION: "profitability",
    SignalCode.PROFITABILITY_DETERIORATION: "profitability",
    SignalCode.INTEREST_COVERAGE_DECLINE: "coverage",
    SignalCode.CASH_FLOW_WEAKENING: "cash_flow",
    SignalCode.NEGATIVE_EQUITY: "leverage",
    SignalCode.UNUSUAL_MOVEMENT: "cross_dimension",
    SignalCode.MULTI_DIMENSION_DETERIORATION: "cross_dimension",
}


# ---------------------------------------------------------------------------
# Rebuilding the three layers


def _trend(ratio_id: str, direction: EconomicDirection, period: str) -> RatioTrend:
    definition = RATIOS_BY_ID[ratio_id]
    conclusive = direction in (
        EconomicDirection.DETERIORATING,
        EconomicDirection.IMPROVING,
        EconomicDirection.STABLE,
    )
    results = tuple(
        RatioResult(
            ratio_id=ratio_id,
            name=definition.name,
            category=definition.category,
            period_label=label,
            value=1.0 if conclusive else None,
            unit=definition.unit,
            status=RatioStatus.CALCULATED if conclusive else RatioStatus.MISSING_INPUT,
            formula=definition.formula,
            formula_display=definition.formula_display,
            inputs={},
        )
        for label in (period,)
    )
    return RatioTrend(
        ratio_id=ratio_id,
        results=results,
        direction=(
            TrendDirection.DECREASING
            if direction is EconomicDirection.DETERIORATING
            else TrendDirection.STABLE
            if conclusive
            else TrendDirection.INSUFFICIENT_DATA
        ),
        economic_direction=direction,
        periods_available=1 if conclusive else 0,
        history_depth=HistoryDepth.ADEQUATE if conclusive else HistoryDepth.LIMITED,
        has_gap=False,
        gap_periods=(),
        absolute_change=None,
        percent_change=None,
        persistence=0,
        baseline_median=None,
        deviation_from_baseline=None,
        unusual_movement=False,
        negative_equity=False,
        data_quality=DataQualityLevel.GOOD,
        reason=None if conclusive else "reconstructed: dimension was INSUFFICIENT_DATA",
    )


def _health_report(observation: Observation) -> FinancialHealthReport:
    """Rebuild a Phase 7 report from the Phase 8 encoding of one.

    `dim_deteriorating_<d>` is `1.0`, `0.0` or `None`, and `features.py` sets
    `None` exactly when Phase 7 said `INSUFFICIENT_DATA` -- so the three-way
    distinction the cross-layer rules read survives the round trip intact. What
    does not survive is the difference between `IMPROVING`, `STABLE` and
    `MIXED`, which the encoding collapsed to `0.0` before this script existed.
    That collapse is conservative for the contradiction rules and against them
    for corroboration: `MIXED` should read as elevated (see
    `evidence._DIMENSION_CONCERN`) and here reads as quiet, so any
    `MODEL_ELEVATED_HEALTH_QUIET` count below is an upper bound and any
    health-based corroboration count is a lower bound.
    """
    features = observation.features
    period = observation.key.fiscal_period_label

    raised: list[Signal] = []
    for code in SignalCode:
        if not features.get(f"signal_{code.value}"):
            continue
        category = SIGNAL_DIMENSION[code]
        ratio_id = REPRESENTATIVE.get(category)
        raised.append(
            Signal(
                code=code,
                category=category,
                ratio_id=ratio_id,
                trend=(
                    _trend(ratio_id, EconomicDirection.DETERIORATING, period) if ratio_id else None
                ),
                evidence=f"{code.value} raised for {period}",
            )
        )

    dimensions: dict[str, DimensionHealth] = {}
    for dimension in DIMENSIONS:
        flag = features.get(f"dim_deteriorating_{dimension}")
        if flag is None:
            status, direction = (
                DimensionStatus.INSUFFICIENT_DATA,
                EconomicDirection.INSUFFICIENT_DATA,
            )
        elif flag >= 1.0:
            status, direction = DimensionStatus.DETERIORATING, EconomicDirection.DETERIORATING
        else:
            status, direction = DimensionStatus.STABLE, EconomicDirection.STABLE
        dimensions[dimension] = DimensionHealth(
            dimension=dimension,
            status=status,
            ratio_trends=(_trend(REPRESENTATIVE[dimension], direction, period),),
            signals=tuple(s for s in raised if s.category == dimension),
        )

    return FinancialHealthReport(
        company=observation.key.company,
        period_label=period,
        periods_considered=(period,),
        analysis_window=5,
        dimensions=dimensions,
        signals=tuple(raised),
        changes_since_previous_period=(),
        data_quality=DataQuality(
            level=DataQualityLevel.GOOD,
            ratios_with_low_confidence_input=(),
            ratios_with_manual_correction=(),
            ratios_with_derived_input=(),
            ratios_with_limited_history=(),
        ),
    )


def _narrative_reports(
    signals: pd.DataFrame, per_filing: pd.DataFrame
) -> dict[str, NarrativeRiskReport]:
    """Rebuild Phase 10's reports from its committed signal dump.

    Every field the assessment layer reads -- code, assertion, specificity,
    section, character span and the quote itself -- is in `nlp_signals.csv`, so
    this is a load rather than a re-derivation. `gated_out` rows are the
    hypothetical and cross-reference matches Phase 10 withholds by default, and
    they are withheld here too: D-035's measurement is that ungated covenant
    language carries a lift of 1.02.
    """
    coverage_columns = [c for c in per_filing.columns if c.startswith("located_")]
    reports: dict[str, NarrativeRiskReport] = {}
    emitted = signals[signals["gated_out"].isna() | (signals["gated_out"] == False)]  # noqa: E712
    by_accession = dict(tuple(emitted.groupby("accession")))

    for row in per_filing.to_dict("records"):
        accession = str(row["accession"])
        found = by_accession.get(accession, pd.DataFrame())
        built: list[NarrativeRiskSignal] = []
        for signal in found.to_dict("records"):
            text = str(signal["quote"])
            built.append(
                NarrativeRiskSignal(
                    code=RiskSignalCode(signal["code"]),
                    label=str(signal["code"]).replace("_", " ").capitalize(),
                    assertion=Assertion(signal["assertion"]),
                    specificity=Specificity(signal["specificity"]),
                    pattern_id=str(signal["pattern_id"]),
                    quote=EvidenceQuote(
                        text=text,
                        char_start=int(signal["char_start"]),
                        char_end=int(signal["char_end"]),
                        section_id=str(signal["section_id"]),
                        trigger_start=0,
                        trigger_end=min(len(text), 1),
                        accession=accession,
                        form=str(row["filed"]) and "10-K",
                        filed=str(row["filed"]),
                    ),
                )
            )
        coverage = tuple(
            SectionCoverage(
                section_id=column.removeprefix("located_"),
                located=bool(row[column]),
                sentences=int(row.get(f"sentences_{column.removeprefix('located_')}") or 0),
                reason=None if row[column] else "section heading not located",
            )
            for column in coverage_columns
        )
        reports[accession] = NarrativeRiskReport(
            cik=int(row["cik"]),
            company=str(row["company"]),
            accession=accession,
            form="10-K",
            filed=str(row["filed"]),
            signals=tuple(built),
            coverage=coverage,
        )
    return reports


# ---------------------------------------------------------------------------
# The model layer, run for real


def _out_of_fold(observations: list[Observation]) -> dict[int, dict[str, Any]]:
    """Out-of-time score, TreeSHAP contributions and within-year percentile.

    The percentile is computed *within the fold's test year*, not across the
    pooled panel. A monitoring product ranks this quarter's filings against
    each other; ranking a 2013 filing against a 2019 one would mix the model's
    drift into the position an analyst reads.
    """
    from credit_risk_copilot.explain.adapters import attributor_for
    from credit_risk_copilot.modeling.model import design_matrix, labels_array

    spec = {s.name: s for s in build_model_specs()}[PRIMARY_MODEL]
    plan = walk_forward_folds(observations)
    assert_temporal_ordering(observations, plan)

    scored: dict[int, dict[str, Any]] = {}
    for fold in plan.folds:
        train = [observations[i] for i in fold.train_indices]
        test = [observations[i] for i in fold.test_indices]
        x_train, names = design_matrix(train, spec.feature_names, add_missing_indicators=False)
        x_test, _ = design_matrix(test, spec.feature_names, add_missing_indicators=False)
        y_train = labels_array(train)
        if len(np.unique(y_train)) < 2:
            continue
        assert spec.estimator_factory is not None
        estimator = spec.estimator_factory()
        estimator.fit(x_train, y_train)
        scores = estimator.predict_proba(x_test)[:, 1]
        attribution = attributor_for(estimator, tuple(names)).attribute(x_test)
        ranks = pd.Series(scores).rank(pct=True) * 100.0
        for position, index in enumerate(fold.test_indices):
            scored[index] = {
                "score": float(scores[position]),
                "percentile": float(ranks.iloc[position]),
                "attribution": attribution,
                "row": position,
                "test_year": fold.test_year,
            }
    return scored


def _explanation(observation: Observation, scored: dict[str, Any]):
    attribution: AttributionResult = scored["attribution"]
    return explain_observation(
        observation=observation,
        attribution=attribution,
        row=scored["row"],
        score=scored["score"],
        # The contributions are on the model's own additive scale and do not
        # reconstruct a probability, so the link score is taken from the
        # attribution itself; `reconstruction_error` then measures what it is
        # meant to measure rather than a scale mismatch.
        link_score=float(attribution.baseline + attribution.contributions[scored["row"]].sum()),
        facts={},
        model_name=PRIMARY_MODEL,
        model_family="gradient_boosting",
        calibration_slope=0.81,
        score_percentile=scored["percentile"],
    )


# ---------------------------------------------------------------------------
# Measurement


def _rates(frame: pd.DataFrame, column: str) -> dict[str, float]:
    event = frame[frame["label"] == 1][column].mean()
    comparison = frame[frame["label"] == 0][column].mean()
    return {
        "rate_event": round(float(event), 4),
        "rate_comparison": round(float(comparison), 4),
        "lift": round(float(event / comparison), 3) if comparison else None,
        "n_event": int(frame[frame["label"] == 1][column].sum()),
        "n_comparison": int(frame[frame["label"] == 0][column].sum()),
    }


#: Bootstrap resamples for the matched-budget interval. Clustered on company,
#: like D-027's evaluation: a company contributes several filings and treating
#: them as independent would narrow every interval by counting the same issuer
#: repeatedly.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260919


def _precision_delta(frame: pd.DataFrame, flag: str) -> float | None:
    selected = frame[frame[flag]]
    k = len(selected)
    if k == 0 or k > len(frame):
        return None
    top_k = frame.nlargest(k, "percentile")
    return float(selected["label"].mean() - top_k["label"].mean())


def _matched_budget(frame: pd.DataFrame, flag: str) -> dict[str, Any] | None:
    """Precision of a combination against the model's top-k at the same k.

    The comparison the phase turns on. `k` is however many filings the
    combination flags; the model's list is its own top `k` by out-of-time
    percentile. Both lists are drawn from the same corpus, so both carry the
    same cohort confound (D-032) -- which is exactly why the *difference*
    between them is readable even though neither precision is a portfolio
    number.

    The interval is what makes the difference readable at all. On 202 filings a
    precision gap of one or two companies is arithmetic noise, and quoting
    `+0.026` without saying so would be the false precision this project keeps
    refusing.
    """
    selected = frame[frame[flag]]
    k = len(selected)
    if k == 0:
        return None
    top_k = frame.nlargest(k, "percentile")
    delta = float(selected["label"].mean() - top_k["label"].mean())

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    companies = frame["cik"].to_numpy()
    unique = np.unique(companies)
    groups = {cik: frame[frame["cik"] == cik] for cik in unique}
    deltas: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        resample = pd.concat([groups[cik] for cik in drawn], ignore_index=True)
        value = _precision_delta(resample, flag)
        if value is not None:
            deltas.append(value)

    return {
        "k": k,
        "alert_rate": round(k / len(frame), 4),
        "combination_precision": round(float(selected["label"].mean()), 4),
        "combination_recall": round(float(selected["label"].sum() / frame["label"].sum()), 4),
        "model_topk_precision": round(float(top_k["label"].mean()), 4),
        "model_topk_recall": round(float(top_k["label"].sum() / frame["label"].sum()), 4),
        "precision_delta": round(delta, 4),
        "precision_delta_ci95": [
            round(float(np.percentile(deltas, 2.5)), 4),
            round(float(np.percentile(deltas, 97.5)), 4),
        ]
        if deltas
        else None,
        # How much of the combination's list the model would have flagged
        # anyway. A combination that selects the same companies is not adding
        # information, whatever its precision says.
        "overlap_with_model_topk": round(
            len(set(selected["accession"]) & set(top_k["accession"])) / k, 4
        ),
    }


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(PHASE8_DIR / "observations_primary.csv")
    observations = [
        o
        for o in observations_from_rows(panel.replace({np.nan: None}).to_dict("records"))
        if o.outcome.is_usable
    ]
    logger.info("Panel: %d usable observations", len(observations))

    scored = _out_of_fold(observations)
    logger.info("Scored %d observations out of time", len(scored))

    per_filing = pd.read_csv(PHASE10_DIR / "nlp_per_filing.csv")
    signal_dump = pd.read_csv(PHASE10_DIR / "nlp_signals.csv")
    narratives = _narrative_reports(signal_dump, per_filing)
    labels = {str(r["accession"]): int(r["label"]) for r in per_filing.to_dict("records")}
    logger.info("Narrative corpus: %d filings", len(narratives))

    by_accession = {o.key.source_accession: i for i, o in enumerate(observations)}
    rows: list[dict[str, Any]] = []
    assessments: dict[str, Assessment] = {}
    gate_refusals = 0
    gate_attempts = 0
    quote_mismatches = 0
    unresolved_citations = 0

    for accession, narrative in narratives.items():
        index = by_accession.get(accession)
        if index is None or index not in scored:
            # A corpus filing the panel never turned into a usable, scored
            # observation. Skipped and counted, never silently imputed.
            continue
        observation = observations[index]
        as_of = date.fromisoformat(str(narrative.filed))
        health = _health_report(observation)
        explanation = _explanation(observation, scored[index])

        assessment = assemble_assessment(
            cik=observation.key.cik,
            company=observation.key.company,
            as_of=as_of,
            health=health,
            health_filing=FilingStamp(accession=accession, form="10-K", filed=as_of),
            explanation=explanation,
            narrative=narrative,
            pipeline_versions={"phase": "11"},
        )
        assessments[accession] = assessment

        # Integrity: every cited ID resolves, and every quote is still the one
        # Phase 10 emitted.
        for finding in (*assessment.contradictions, *assessment.corroborations):
            unresolved_citations += len(assessment.validate_citations(finding.cited))
        source_quotes = {s.quote.text for s in narrative.signals}
        for item in assessment.evidence:
            if item.quote is not None and item.quote not in source_quotes:
                quote_mismatches += 1

        # FR-05 has to bite: the same assembly one day earlier must be refused,
        # because the filing did not exist yet.
        gate_attempts += 1
        try:
            assemble_assessment(
                cik=observation.key.cik,
                company=observation.key.company,
                as_of=as_of - timedelta(days=1),
                health=health,
                health_filing=FilingStamp(accession=accession, form="10-K", filed=as_of),
                explanation=explanation,
                narrative=narrative,
                gate=AsOfGate(as_of=as_of - timedelta(days=1)),
            )
        except AsOfViolation:
            gate_refusals += 1

        contradiction_codes = {f.code for f in assessment.contradictions}
        corroboration_codes = {f.code for f in assessment.corroborations}
        row: dict[str, Any] = {
            "accession": accession,
            "cik": observation.key.cik,
            "company": observation.key.company,
            "filed": as_of.isoformat(),
            "test_year": scored[index]["test_year"],
            "label": labels[accession],
            "score": scored[index]["score"],
            "percentile": scored[index]["percentile"],
            "n_evidence": len(assessment.evidence),
            "n_contradictions": len(assessment.contradictions),
            "n_corroborations": len(assessment.corroborations),
            "artefact_share": artefact_share(assessment.evidence),
        }
        for code in ContradictionCode:
            row[f"contra_{code.value}"] = code in contradiction_codes
        for code in CorroborationCode:
            row[f"corrob_{code.value}"] = code in corroboration_codes
        rows.append(row)

    frame = pd.DataFrame(rows)
    frame.to_csv(OUT_DIR / "assessment_findings.csv", index=False)
    logger.info("Assembled %d assessments", len(frame))

    # Single-layer baselines, defined on the same evidence the rules read.
    frame["layer_model"] = frame["percentile"] >= 90.0
    frame["layer_narrative"] = [
        any(
            item.detail.get("assertion") == "asserted" and item.detail.get("specificity") == "high"
            for item in assessments[a].evidence
        )
        for a in frame["accession"]
    ]
    frame["layer_health"] = [
        any(
            item.kind.value == "dimension_status" and item.detail.get("status") == "deteriorating"
            for item in assessments[a].evidence
        )
        for a in frame["accession"]
    ]

    summary: dict[str, Any] = {
        "corpus": {
            "filings": int(len(frame)),
            "events": int(frame["label"].sum()),
            "base_rate": round(float(frame["label"].mean()), 4),
            "note": (
                "The Phase 10 corpus is deliberately year-matched between cohorts, so the"
                " base rate is near 0.5 by construction. Precision figures below are"
                " comparisons between methods on one corpus, never portfolio precision."
            ),
            "test_years": sorted(frame["test_year"].unique().tolist()),
            "corpus_filings_without_a_scored_observation": int(len(narratives) - len(frame)),
        },
        "integrity": {
            "unresolved_citations": unresolved_citations,
            "quote_mismatches": quote_mismatches,
            "asof_gate_attempts": gate_attempts,
            "asof_gate_refusals": gate_refusals,
            "evidence_per_assessment_median": float(frame["n_evidence"].median()),
        },
        "filing_artefact_share": {
            "note": (
                "Share of the primary model's attribution coming from the missingness and"
                " data_quality groups -- how much of a prediction is about the filing's"
                " completeness rather than the company. The SCORE_NOT_EVIDENCE_BACKED"
                " threshold is read off these percentiles."
            ),
            "percentiles": {
                str(q): round(float(frame["artefact_share"].quantile(q / 100)), 4)
                for q in (5, 25, 50, 75, 90, 95, 99)
            },
            "max": round(float(frame["artefact_share"].max()), 4),
        },
        "single_layers": {
            name: {**_rates(frame, name), **(_matched_budget(frame, name) or {})}
            for name in ("layer_model", "layer_narrative", "layer_health")
        },
        "contradictions": {
            code.value: _rates(frame, f"contra_{code.value}") for code in ContradictionCode
        },
        "corroborations": {
            code.value: {
                **_rates(frame, f"corrob_{code.value}"),
                **(_matched_budget(frame, f"corrob_{code.value}") or {}),
            }
            for code in CorroborationCode
        },
    }

    # Determinism: a second, independent assembly of the same inputs must
    # produce identical evidence IDs, or every stored citation is worthless.
    sample = list(assessments)[:25]
    repeat_ok = True
    for accession in sample:
        original = assessments[accession]
        index = by_accession[accession]
        rebuilt = assemble_assessment(
            cik=original.cik,
            company=original.company,
            as_of=original.as_of,
            health=_health_report(observations[index]),
            health_filing=FilingStamp(accession=accession, form="10-K", filed=original.as_of),
            explanation=_explanation(observations[index], scored[index]),
            narrative=narratives[accession],
            pipeline_versions={"phase": "11"},
        )
        if [i.evidence_id for i in rebuilt.evidence] != [i.evidence_id for i in original.evidence]:
            repeat_ok = False
    summary["integrity"]["evidence_ids_stable_on_reassembly"] = repeat_ok
    summary["integrity"]["reassembly_sample"] = len(sample)

    # How often each finding co-occurs with another, so the doc can say whether
    # the rules are measuring one thing under seven names.
    overlap: dict[str, dict[str, int]] = defaultdict(dict)
    flags = [f"contra_{c.value}" for c in ContradictionCode] + [
        f"corrob_{c.value}" for c in CorroborationCode
    ]
    for left in flags:
        for right in flags:
            overlap[left][right] = int((frame[left] & frame[right]).sum())
    pd.DataFrame(overlap).to_csv(OUT_DIR / "finding_overlap.csv")

    (OUT_DIR / "phase11_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote %s", OUT_DIR / "phase11_summary.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
