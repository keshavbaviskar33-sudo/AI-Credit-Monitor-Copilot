"""Phase 17, debt 4: give Phase 10's recall a number.

Phase 10 reported precision (73.4%) and refused to report recall, because the
pool its sweep emitted had never been labelled and "quoting a recall figure
from a handful of rows would be worse than quoting none"
([nlp_risk_signals.md §9](../docs/nlp_risk_signals.md)). The pool is now
labelled -- 150 candidates in `evaluation/phase10_recall_labels.csv`, each one
`true_signal`, `boilerplate` or `unrelated`, with a note on every judgement
call -- so the arithmetic can run.

**What the number is, and what it is not.** The denominator is the true
instances *the sweep found*, and the sweep is bare topic keywords
(`recall_sweep.py`). A disclosure phrased in words neither matcher contains is
invisible to both, so this is recall **relative to the sweep's reach** and is an
upper bound on the catalog's true recall, never an estimate of it. That
qualification is not boilerplate: it is the reason the figure is reportable at
all.

**The labelling rule, stated so it can be disagreed with.** `true_signal` means
the sentence *asserts* the condition its code names, about this filer. A
hypothetical ("if we breach"), a definition, an accounting policy, a negation
("no impairment was recorded") and a statement about somebody else's distress
(a customer's bankruptcy) are all not instances -- because the catalog is
deliberately built to exclude them ([D-035](../docs/decision_log.md)), so
counting them in the denominator would score the layer against a target it was
designed not to hit.

    uv run python scripts/phase17_recall.py
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk_copilot.logging_config import configure_logging

logger = logging.getLogger(__name__)

LABELS = Path("evaluation/phase10_recall_labels.csv")
OUT_DIR = Path("data/processed/phase17")

#: The three codes Phase 10 measured at the highest lift and at 13/13
#: precision. Whether the pool can say anything about *their* recall is a
#: separate question from the headline, and it is asked explicitly below.
HIGHEST_LIFT = ("going_concern_doubt", "bankruptcy_contemplated", "delisting_notice")


def wilson(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    """Wilson score interval -- the right one at these counts.

    The normal approximation is unusable here: several per-code cells have
    single-digit denominators, where it produces intervals that run past 0 or 1
    and quietly imply a precision the sample cannot support.
    """
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denominator
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    labels = pd.read_csv(LABELS)
    if labels["verdict"].isna().any() or (labels["verdict"] == "").any():
        raise ValueError("The recall pool still has unlabelled rows; recall is not reportable.")

    true_signals = labels[labels["verdict"] == "true_signal"]
    caught = int(true_signals["caught_by_catalog"].sum())
    total = len(true_signals)

    per_code: dict[str, Any] = {}
    for code, group in labels.groupby("code"):
        instances = group[group["verdict"] == "true_signal"]
        per_code[str(code)] = {
            "candidates": int(len(group)),
            "true_instances": int(len(instances)),
            "caught": int(instances["caught_by_catalog"].sum()),
            "recall": (
                round(float(instances["caught_by_catalog"].mean()), 4) if len(instances) else None
            ),
            "recall_ci95": wilson(int(instances["caught_by_catalog"].sum()), len(instances)),
        }

    # The pool's own precision check. Every row the catalog claimed should be a
    # true instance; if one is not, the sweep has found a false positive the
    # precision sample missed, which is worth knowing separately.
    claimed = labels[labels["caught_by_catalog"]]
    claimed_true = int((claimed["verdict"] == "true_signal").sum())

    silent_codes = sorted(code for code, stats in per_code.items() if stats["true_instances"] == 0)

    summary: dict[str, Any] = {
        "what_this_measures": (
            "Recall of the Phase 10 catalog relative to the reach of the over-broad keyword"
            " sweep in nlp/recall_sweep.py. Not true recall: a disclosure phrased in words"
            " neither matcher contains is invisible to both, so this is an upper bound."
        ),
        "pool": {
            "candidates": int(len(labels)),
            "true_signal": total,
            "boilerplate": int((labels["verdict"] == "boilerplate").sum()),
            "unrelated": int((labels["verdict"] == "unrelated").sum()),
        },
        "recall": {
            "caught": caught,
            "true_instances": total,
            "recall": round(caught / total, 4) if total else None,
            "recall_ci95": wilson(caught, total),
        },
        "pool_precision": {
            "note": (
                "Of the pool rows the catalog claimed, how many the labeller agrees with."
                " Independent of the Phase 10 precision sample, which was drawn from the"
                " catalog's own output rather than from the sweep's."
            ),
            "claimed": int(len(claimed)),
            "agreed": claimed_true,
            "precision": round(claimed_true / len(claimed), 4) if len(claimed) else None,
        },
        "per_code": dict(sorted(per_code.items())),
        "codes_the_pool_cannot_speak_about": silent_codes,
        "highest_lift_codes": {
            code: per_code.get(code, {"true_instances": 0, "caught": 0, "recall": None})
            for code in HIGHEST_LIFT
        },
    }

    (OUT_DIR / "phase17_recall.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote %s", OUT_DIR / "phase17_recall.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
