"""Phase 17, debt 5: close A-09, A-11, A-13 and A-14.

[D-045](../docs/decision_log.md) named these four as "the four that decide
whether the predictive layer means anything". Each has sat at **Open** since
Phase 1 with a validation plan and no measurement. This script runs the
measurements; the verdicts go into [assumptions.md](../docs/assumptions.md).

Each assumption gets the test its own validation plan asked for, and where the
project has since made that test impossible or meaningless, that is reported as
the finding rather than worked around:

- **A-09 (feature reproducibility).** Written when the plan was to train on a
  third-party dataset and serve from SEC XBRL, so the features would have had
  two definitions that had to agree. [D-013](../docs/decision_log.md) chose a
  self-built corpus instead, and there is now exactly one feature pipeline,
  used at both training and inference. The assumption's original form is
  dissolved. Its residual is real and is what gets measured here: the same
  fiscal period, resolved later, does not always give the same number.
- **A-11 (bankruptcy as a distress proxy).** Measured as the proxy's own
  failure mode -- filings that disclose severe distress in the filer's own
  words and are labelled 0 because no petition followed.
- **A-13 (enough events for an out-of-time test).** Counted per walk-forward
  fold, on both the Phase 8 panel and the eligibility-matched panel this phase
  built, against the interval widths those event counts produce.
- **A-14 (base-rate framing).** The panel base rates are compared against a
  bankruptcy rate computed from this project's own point-in-time filer
  population, which is the closest thing to a real-world rate the data
  supports.

    uv run python scripts/phase17_assumptions.py
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from credit_risk_copilot.logging_config import configure_logging
from credit_risk_copilot.modeling.dataset import observations_from_rows
from credit_risk_copilot.modeling.labels import load_event_table
from credit_risk_copilot.modeling.splits import walk_forward_folds

logger = logging.getLogger(__name__)

PHASE8_DIR = Path("data/processed/phase8")
PHASE9_DIR = Path("data/processed/phase9")
PHASE10_DIR = Path("data/processed/phase10")
OUT_DIR = Path("data/processed/phase17")
BRD_CASES = Path("data/raw/brd/cases.csv")

#: Disclosures that name a condition a creditor would call distress. Every one
#: is read only when the filer *asserts* it -- the gate D-035 built -- because
#: ungated covenant language appears in 59% of filings of companies that did
#: not fail, which is the measurement that makes this list worth anything.
DISTRESS_CODES = (
    "going_concern_doubt",
    "bankruptcy_contemplated",
    "delisting_notice",
    "debt_default_or_acceleration",
    "covenant_breach",
    "debt_restructuring",
)

#: BRD requires a 10-K within roughly three years before the petition. Used
#: here to build the denominator the same way BRD builds its numerator.
BRD_LOOKBACK_YEARS = 3


# ---------------------------------------------------------------------------
# A-09: one pipeline, and the residual it still carries


def a09() -> dict[str, Any]:
    """How much a fact moves when the same period is resolved from a later filing.

    `qm04_restatements.csv` is Phase 8's own measurement of exactly this: every
    (concept, period) whose value changed between the filing that first
    reported it and a later one that restated it. It is the residual A-09
    reduces to once training and serving share a pipeline, because the one way
    the two can still disagree is *when* the question is asked.
    """
    restatements = pd.read_csv(PHASE8_DIR / "qm04_restatements.csv")
    qm04 = json.loads((PHASE8_DIR / "qm04_summary.json").read_text(encoding="utf-8"))
    relative = restatements["relative_difference"].abs().dropna()

    by_concept = (
        restatements.groupby("concept")["relative_difference"]
        .apply(lambda s: round(float(s.abs().median()), 4))
        .sort_values(ascending=False)
    )

    return {
        "original_form": (
            "A-09 assumed two feature definitions -- a third-party training set's and SEC"
            " XBRL's -- that had to be made equivalent. D-013 chose a self-built corpus, so"
            " modeling/features.py is the only definition and is used at both training and"
            " inference. There is no second definition to skew against."
        ),
        "residual_measured": (
            "The surviving risk is temporal, not definitional: resolving the same fiscal"
            " period from a later filing can return a different number. D-008 and D-026"
            " answer it by construction (as-filed, point-in-time), and the size of what"
            " that choice avoids is below."
        ),
        "companies": qm04["companies"],
        "filings_resolved": qm04["filings_resolved"],
        "restatements": int(len(restatements)),
        "by_category": qm04["restatements"]["by_category"],
        "absolute_relative_difference": {
            "median": round(float(relative.median()), 4),
            "p75": round(float(relative.quantile(0.75)), 4),
            "p90": round(float(relative.quantile(0.90)), 4),
            "max": round(float(relative.max()), 4),
            "share_above_5pct": round(float((relative > 0.05).mean()), 4),
            "share_above_20pct": round(float((relative > 0.20).mean()), 4),
        },
        "median_absolute_difference_by_concept": by_concept.head(10).to_dict(),
        "not_measured": (
            "Propagation from restated facts to ratio and feature values is not measured;"
            " these are fact-level differences on the 12-company golden set."
        ),
    }


# ---------------------------------------------------------------------------
# A-11: what the label misses


def a11() -> dict[str, Any]:
    """Filings that disclose distress in the filer's own words and never fail.

    The question is not whether bankruptcy is *a* distress signal -- it plainly
    is -- but whether it is a reasonable *proxy* for distress, which fails in
    one direction: a company can be in severe distress, disclose it, and never
    file. Those filings are labelled 0, so the model is trained to call them
    safe.
    """
    signals = pd.read_csv(PHASE10_DIR / "nlp_signals.csv")
    per_filing = pd.read_csv(PHASE10_DIR / "nlp_per_filing.csv")
    labels = {str(r["accession"]): int(r["label"]) for r in per_filing.to_dict("records")}

    emitted = signals[
        (signals["gated_out"].isna() | (signals["gated_out"] == False))  # noqa: E712
        & (signals["assertion"] == "asserted")
    ]

    per_code: dict[str, Any] = {}
    for code in DISTRESS_CODES:
        found = emitted[emitted["code"] == code]
        accessions = sorted(set(found["accession"].astype(str)))
        followed = [a for a in accessions if labels.get(a) == 1]
        per_code[code] = {
            "filings_disclosing": len(accessions),
            "followed_by_petition": len(followed),
            "not_followed": len(accessions) - len(followed),
            "share_followed": (round(len(followed) / len(accessions), 4) if accessions else None),
        }

    any_distress = sorted(
        set(emitted[emitted["code"].isin(DISTRESS_CODES)]["accession"].astype(str))
    )
    any_followed = [a for a in any_distress if labels.get(a) == 1]

    # The strongest single marker: an auditor or management statement of
    # substantial doubt. If bankruptcy were a clean proxy for distress, this
    # should be followed by a petition most of the time.
    gc = per_code["going_concern_doubt"]

    return {
        "corpus_note": (
            "The Phase 10 corpus is year-matched between cohorts, base rate 0.495. These are"
            " conditional rates on that corpus, not portfolio rates -- but the direction of"
            " the miss is not a property of the sampling, because a filing that asserts"
            " going-concern doubt and is labelled 0 is mislabelled as safe on any corpus."
        ),
        "corpus_filings": int(len(per_filing)),
        "corpus_base_rate": round(float(per_filing["label"].mean()), 4),
        "per_code": per_code,
        "any_distress_disclosure": {
            "filings": len(any_distress),
            "followed_by_petition": len(any_followed),
            "not_followed": len(any_distress) - len(any_followed),
            "share_followed": (
                round(len(any_followed) / len(any_distress), 4) if any_distress else None
            ),
        },
        "going_concern_doubt_not_followed": gc["not_followed"],
    }


# ---------------------------------------------------------------------------
# A-13: enough events, per fold


def _fold_events(path: Path, name: str) -> dict[str, Any]:
    frame = pd.read_csv(path)
    observations = [
        o
        for o in observations_from_rows(frame.replace({np.nan: None}).to_dict("records"))
        if o.outcome.is_usable
    ]
    plan = walk_forward_folds(observations)
    per_fold = []
    for fold in plan.folds:
        labels = [observations[i].outcome.label for i in fold.test_indices]
        per_fold.append(
            {
                "test_year": fold.test_year,
                "test_rows": len(labels),
                "events": int(sum(1 for value in labels if value == 1)),
            }
        )
    counts = [f["events"] for f in per_fold]
    return {
        "panel": name,
        "rows": len(observations),
        "events": sum(1 for o in observations if o.outcome.label == 1),
        "folds": len(per_fold),
        "per_fold": per_fold,
        "events_per_fold_min": min(counts) if counts else None,
        "events_per_fold_median": int(np.median(counts)) if counts else None,
        "folds_with_fewer_than_10_events": sum(1 for c in counts if c < 10),
    }


def a13() -> dict[str, Any]:
    panels = [
        _fold_events(PHASE8_DIR / "observations_primary.csv", "phase8_survivor"),
        _fold_events(PHASE9_DIR / "observations_pit.csv", "phase9_point_in_time"),
    ]
    eligibility = OUT_DIR / "phase17_eligibility_matched.json"
    intervals: dict[str, Any] = {}
    if eligibility.exists():
        summary = json.loads(eligibility.read_text(encoding="utf-8"))
        for arm in ("unmatched_point_in_time", "size_matched", "eligibility_matched"):
            for model, stats in summary[arm].items():
                if not isinstance(stats, dict) or "bankruptcy_roc_auc_ci" not in stats:
                    continue
                interval = stats["bankruptcy_roc_auc_ci"]
                family = "logistic" if model.startswith("logistic") else "boosting"
                intervals[f"{arm}/{family}"] = {
                    "roc_auc": stats["bankruptcy_roc_auc"],
                    "ci95": interval,
                    "width": round(interval[1] - interval[0], 4) if interval else None,
                }

    return {
        "question": (
            "Are there enough positive events for the out-of-time test to mean anything?"
            " Answered as event counts per walk-forward fold and as the width of the"
            " intervals those counts produce."
        ),
        "panels": panels,
        "interval_widths": intervals,
    }


# ---------------------------------------------------------------------------
# A-14: three base rates from three designs, and a real one


def a14() -> dict[str, Any]:
    filers = pd.read_csv(PHASE9_DIR / "pit_filers.csv")
    filers["year"] = filers["filed"].astype(str).str.slice(0, 4).astype(int)
    events = load_event_table(BRD_CASES)

    # Denominator: distinct annual filers in year Y. Numerator: BRD petitions
    # in year Y by a company that filed an annual report within the previous
    # three years -- BRD's own "public" condition, applied to build the rate
    # the same way BRD built the cases.
    filers_by_year: dict[int, set[int]] = {}
    for year, group in filers.groupby("year"):
        filers_by_year[int(year)] = set(group["cik"].astype(int))

    petitions_by_year: Counter[int] = Counter()
    for cik, cases in events.cases_by_cik.items():
        for case in cases:
            year = case.filed.year
            if year not in filers_by_year:
                continue
            recent = any(
                cik in filers_by_year.get(year - back, set())
                for back in range(0, BRD_LOOKBACK_YEARS + 1)
            )
            if recent:
                petitions_by_year[year] += 1

    per_year = {
        str(year): {
            "annual_filers": len(filers_by_year[year]),
            "brd_petitions": petitions_by_year.get(year, 0),
            "rate": round(petitions_by_year.get(year, 0) / len(filers_by_year[year]), 5),
        }
        for year in sorted(filers_by_year)
    }
    total_filers = sum(len(v) for v in filers_by_year.values())
    total_petitions = sum(petitions_by_year.get(y, 0) for y in filers_by_year)

    design_rates: dict[str, Any] = {
        "phase10_narrative_corpus": 0.4958,
        "phase11_assessment_corpus": 0.4950,
    }
    eligibility = OUT_DIR / "phase17_eligibility_matched.json"
    if eligibility.exists():
        summary = json.loads(eligibility.read_text(encoding="utf-8"))
        for arm in ("unmatched_point_in_time", "size_matched", "eligibility_matched"):
            for stats in summary[arm].values():
                if isinstance(stats, dict) and "pr_auc_baseline" in stats:
                    design_rates[arm] = stats["pr_auc_baseline"]
                    break

    model_summary = json.loads((PHASE8_DIR / "model_summary.json").read_text(encoding="utf-8"))
    primary = model_summary.get("primary_model")

    return {
        "question": (
            "A-14 assumed the training base rate differs from any real portfolio's, so raw"
            " probabilities need careful framing. The assumption is testable by measuring"
            " both numbers."
        ),
        "base_rate_by_design": design_rates,
        "real_world_rate": {
            "method": (
                "BRD petitions per year over distinct SEC annual filers per year, from the"
                " point-in-time filer population D-032 built. Both restricted to companies"
                f" that filed an annual report within {BRD_LOOKBACK_YEARS} years, which is"
                " BRD's own 'public' condition."
            ),
            "per_year": per_year,
            "pooled_filer_years": total_filers,
            "pooled_petitions": total_petitions,
            "pooled_rate": round(total_petitions / total_filers, 5) if total_filers else None,
            "caveat": (
                "This is the rate among *all* annual filers. BRD records only large"
                " bankruptcies, so it is the rate at which a filer suffers a BRD-recordable"
                " bankruptcy -- the rate among BRD-*eligible* filers alone is higher, by"
                " roughly the reciprocal of the eligible share."
            ),
        },
        "primary_model": primary,
        "framing_already_enforced": (
            "D-033 makes the output a ranking position in the type: score_percentile sits"
            " beside score, and any model whose calibration slope falls outside [0.8, 1.25]"
            " carries a NOT_CALIBRATED caveat automatically."
        ),
    }


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary = {"A-09": a09(), "A-11": a11(), "A-13": a13(), "A-14": a14()}
    (OUT_DIR / "phase17_assumptions.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    logger.info("Wrote %s", OUT_DIR / "phase17_assumptions.json")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
