"""Phase 12: measure the grounding validator against drafts that are known to be wrong.

The validator is this phase's deliverable, and there is only one honest way to
measure one. A live model gives you whatever it happened to produce that day:
if it behaves, you learn nothing about what the validator catches, and if it
misbehaves you learn about one failure out of many. So the measurement here is
**fault injection** -- take a draft that is correct by construction, break it
in a named way, and ask whether the validator says so.

Two numbers come out, and they pull in opposite directions:

- **False-positive rate.** How often a *correct* draft is rejected. This has to
  be zero. A validator that rejects good drafts is not strict, it is broken,
  and it gets switched off in week one. The reference drafts deliberately do
  the things a real model does and a naive validator fails on -- round 97.8312
  to "97.8", quote a clause rather than the whole sentence, name a fiscal
  period that exists only as text.
- **Detection rate per fault class.** How often an injected fault is caught.

A third number is reported because it is a real limitation rather than a
success: with ~30 evidence items per assessment each carrying numbers, a
fabricated figure can land on a *different* real value and be downgraded from
a rejection to a flag. That collision rate is measured rather than assumed to
be negligible.

The sensitivity sweep answers the question the precision rule invites: perturb
a stated number by k units in the last place it was written, and at what k does
the validator start to notice? Anything less than half a unit must pass -- that
is rounding -- and anything more must fail.

    uv run python scripts/phase12_grounding.py

No API key is used or needed. `scripts/phase12_synthesize.py` is the live path.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from phase11_assess import (  # noqa: E402
    PHASE8_DIR,
    PHASE10_DIR,
    _explanation,
    _health_report,
    _narrative_reports,
    _out_of_fold,
)

from credit_risk_copilot.assessment import FilingStamp, assemble_assessment  # noqa: E402
from credit_risk_copilot.assessment.models import Assessment, EvidenceKind  # noqa: E402
from credit_risk_copilot.logging_config import configure_logging  # noqa: E402
from credit_risk_copilot.modeling.dataset import observations_from_rows  # noqa: E402
from credit_risk_copilot.synthesis.prompt import build_request, evidence_pack  # noqa: E402
from credit_risk_copilot.synthesis.schema import (  # noqa: E402
    Claim,
    ClaimKind,
    DraftSynthesis,
    FailureCode,
)
from credit_risk_copilot.synthesis.validator import validate  # noqa: E402

logger = logging.getLogger(__name__)
OUT_DIR = Path("data/processed/phase12")

#: Opus 5 list price, $ per million tokens (skill reference, 2026-06-24).
INPUT_PRICE_PER_MTOK = 5.00
OUTPUT_PRICE_PER_MTOK = 25.00
#: No tokenizer is available offline, so prompt size is reported in characters
#: and converted at the conventional English ratio. The assumption is named in
#: the output rather than buried, and a live run replaces the estimate with
#: `usage.input_tokens`.
CHARS_PER_TOKEN = 4.0


# ---------------------------------------------------------------------------
# A draft that is correct by construction


def reference_draft(assessment: Assessment) -> DraftSynthesis | None:
    """The draft a perfectly behaved model would return for this assessment.

    Built to exercise the rules that are hard rather than the ones that are
    easy: the headline rounds a stored percentile to one decimal, the
    narrative claim quotes a *clause* of the stored sentence, and the
    dimension claim names a fiscal period that exists only as text inside a
    summary. A validator that fails on any of those fails on every real draft.
    """
    scores = assessment.of_kind(EvidenceKind.MODEL_SCORE)
    dimensions = [
        item
        for item in assessment.of_kind(EvidenceKind.DIMENSION_STATUS)
        if item.detail.get("status") == "deteriorating"
    ]
    if not scores or not dimensions:
        return None
    score = scores[0]
    percentile = score.detail.get("score_percentile")
    if not isinstance(percentile, (int, float)):
        return None

    claims: list[Claim] = []
    for item in dimensions[:2]:
        claims.append(
            Claim(
                kind=ClaimKind.FINDING,
                text=f"{item.dimension} is deteriorating over {assessment.period_label}.",
                evidence_ids=(item.evidence_id,),
                dimension=item.dimension,
            )
        )

    narrative = [
        item
        for item in assessment.of_kind(EvidenceKind.NARRATIVE_SIGNAL)
        if item.quote and item.detail.get("assertion") == "asserted"
    ]
    if narrative:
        item = narrative[0]
        assert item.quote is not None
        words = item.quote.split()
        claims.append(
            Claim(
                kind=ClaimKind.FINDING,
                text="The filing states a risk condition about the company itself.",
                evidence_ids=(item.evidence_id,),
                # A clause, not the whole sentence: shortening is not
                # fabricating, and a real draft shortens.
                quote=" ".join(words[1 : max(2, len(words) - 1)]),
            )
        )

    for finding in assessment.contradictions[:1]:
        cited = finding.cited or (score.evidence_id,)
        claims.append(
            Claim(
                kind=ClaimKind.DISAGREEMENT,
                text="Two analytical layers disagree about this company's position.",
                evidence_ids=cited,
                dimension=finding.dimension,
            )
        )

    if assessment.layers_absent:
        claims.append(
            Claim(
                kind=ClaimKind.LIMITATION,
                text="One analytical layer produced no evidence for this filing.",
                evidence_ids=(score.evidence_id,),
            )
        )

    claims.append(
        Claim(
            kind=ClaimKind.CHECK,
            text="Open the filing and confirm the covenant position in the debt footnote.",
        )
    )

    return DraftSynthesis(
        headline=Claim(
            kind=ClaimKind.FINDING,
            text=(
                f"{assessment.company} ranks at the {percentile:.1f}th percentile of the"
                " monitored population for this period."
            ),
            evidence_ids=(score.evidence_id,),
        ),
        claims=tuple(claims),
    )


# ---------------------------------------------------------------------------
# Faults


def _replace_headline(draft: DraftSynthesis, **update: Any) -> DraftSynthesis:
    return draft.model_copy(update={"headline": draft.headline.model_copy(update=update)})


def fabricated_citation(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis:
    return _replace_headline(draft, evidence_ids=("EV-MS-deadbeef",))


def fabricated_number(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis:
    text = draft.headline.text
    percentile = float(text.split("the ")[1].split("th")[0])
    # Move it far enough that no rounding rule could reach the real value.
    wrong = (percentile + 37.3) % 100
    return _replace_headline(draft, text=text.replace(f"{percentile:.1f}", f"{wrong:.1f}"))


def dropped_citation(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis:
    return _replace_headline(draft, evidence_ids=())


def reworded_quote(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis | None:
    claims = list(draft.claims)
    for index, claim in enumerate(claims):
        if claim.quote:
            claims[index] = claim.model_copy(update={"quote": claim.quote + " and materially so"})
            return draft.model_copy(update={"claims": tuple(claims)})
    return None


def probability_claim(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis:
    return draft.model_copy(
        update={
            "claims": draft.claims
            + (
                Claim(
                    kind=ClaimKind.FINDING,
                    text="There is a 72% probability of default within the next twelve months.",
                    evidence_ids=draft.headline.evidence_ids,
                ),
            )
        }
    )


def omitted_contradiction(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis | None:
    if not assessment.contradictions:
        return None
    return draft.model_copy(
        update={"claims": tuple(c for c in draft.claims if c.kind is not ClaimKind.DISAGREEMENT)}
    )


def miscited_number(draft: DraftSynthesis, assessment: Assessment) -> DraftSynthesis | None:
    """A real figure attached to a claim citing different evidence."""
    others = [
        item
        for item in assessment.of_kind(EvidenceKind.DIMENSION_STATUS)
        if item.evidence_id not in draft.headline.evidence_ids
    ]
    if not others:
        return None
    return _replace_headline(draft, evidence_ids=(others[0].evidence_id,))


#: `(name, mutation, the code that must fire, whether the verdict must flip)`.
FAULTS: tuple[tuple[str, Any, FailureCode, bool], ...] = (
    ("fabricated_citation", fabricated_citation, FailureCode.UNRESOLVED_CITATION, True),
    ("fabricated_number", fabricated_number, FailureCode.UNGROUNDED_NUMBER, True),
    ("dropped_citation", dropped_citation, FailureCode.UNCITED_CLAIM, True),
    ("reworded_quote", reworded_quote, FailureCode.NON_VERBATIM_QUOTE, True),
    ("probability_claim", probability_claim, FailureCode.FORBIDDEN_CONCLUSION, True),
    ("omitted_contradiction", omitted_contradiction, FailureCode.OMITTED_CONTRADICTION, True),
    ("miscited_number", miscited_number, FailureCode.MISCITED_NUMBER, False),
)


def sensitivity_sweep(draft: DraftSynthesis, assessment: Assessment) -> dict[str, str]:
    """Perturb the headline percentile by k units in the last stated place.

    The precision rule promises that anything under half a unit is rounding and
    anything over it is a different number. This is that promise, measured.

    The outcome is three-valued rather than boolean, because a perturbed value
    can land on a *different* real number in the same assessment and be caught
    as a mis-citation instead of a fabrication. Collapsing that into "not
    detected" would understate the validator, and into "detected" would hide
    that the verdict was a flag rather than a rejection.
    """
    text = draft.headline.text
    percentile = float(text.split("the ")[1].split("th")[0])
    outcome: dict[str, str] = {}
    for k in (0.2, 0.4, 0.6, 1.0, 2.0, 10.0):
        shifted = percentile + k * 0.1  # one unit in the last place of "%.1f"
        mutated = _replace_headline(draft, text=text.replace(f"{percentile:.1f}", f"{shifted:.1f}"))
        codes = validate(mutated, assessment).codes()
        if FailureCode.UNGROUNDED_NUMBER in codes:
            outcome[f"k={k}"] = "rejected"
        elif FailureCode.MISCITED_NUMBER in codes:
            outcome[f"k={k}"] = "flagged"
        else:
            outcome[f"k={k}"] = "passed"
    return outcome


def main() -> None:
    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(PHASE8_DIR / "observations_primary.csv")
    observations = [
        o
        for o in observations_from_rows(panel.replace({np.nan: None}).to_dict("records"))
        if o.outcome.is_usable
    ]
    scored = _out_of_fold(observations)
    per_filing = pd.read_csv(PHASE10_DIR / "nlp_per_filing.csv")
    narratives = _narrative_reports(pd.read_csv(PHASE10_DIR / "nlp_signals.csv"), per_filing)
    by_accession = {o.key.source_accession: i for i, o in enumerate(observations)}

    assessments: list[Assessment] = []
    for accession, narrative in narratives.items():
        index = by_accession.get(accession)
        if index is None or index not in scored:
            continue
        observation = observations[index]
        from datetime import date

        as_of = date.fromisoformat(str(narrative.filed))
        assessments.append(
            assemble_assessment(
                cik=observation.key.cik,
                company=observation.key.company,
                as_of=as_of,
                health=_health_report(observation),
                health_filing=FilingStamp(accession=accession, form="10-K", filed=as_of),
                explanation=_explanation(observation, scored[index]),
                narrative=narrative,
                pipeline_versions={"phase": "12"},
            )
        )
    logger.info("Rebuilt %d assessments", len(assessments))

    rows: list[dict[str, Any]] = []
    detection: dict[str, Counter] = defaultdict(Counter)
    sweep: Counter = Counter()
    sweep_total = 0
    prompt_chars: list[int] = []
    skipped = 0

    for assessment in assessments:
        draft = reference_draft(assessment)
        if draft is None:
            skipped += 1
            continue
        baseline = validate(draft, assessment)
        prompt_chars.append(len(evidence_pack(assessment)))

        rows.append(
            {
                "cik": assessment.cik,
                "company": assessment.company,
                "as_of": assessment.as_of.isoformat(),
                "evidence_items": len(assessment.evidence),
                "claims": len(draft.all_claims),
                "reference_accepted": baseline.accepted,
                "reference_findings": ", ".join(f.code.value for f in baseline.findings),
                "prompt_chars": len(evidence_pack(assessment)),
            }
        )

        for name, mutate, expected, must_reject in FAULTS:
            mutated = mutate(draft, assessment)
            if mutated is None:
                detection[name]["not_applicable"] += 1
                continue
            report = validate(mutated, assessment)
            detection[name]["applicable"] += 1
            if expected in report.codes():
                detection[name]["detected"] += 1
            elif name == "fabricated_number" and FailureCode.MISCITED_NUMBER in report.codes():
                # The fabricated value landed on a different real number in the
                # same assessment, so it was caught but downgraded to a flag.
                detection[name]["detected_as_flag"] += 1
            if report.accepted is not must_reject:
                detection[name]["verdict_correct"] += 1

        for key, verdict in sensitivity_sweep(draft, assessment).items():
            sweep[f"{key}|{verdict}"] += 1
        sweep_total += 1

    frame = pd.DataFrame(rows)
    frame.to_csv(OUT_DIR / "grounding_faults.csv", index=False)

    sample = build_request(assessments[0])
    (OUT_DIR / "example_prompt.txt").write_text(
        sample.system + "\n\n" + "=" * 70 + "\n\n" + sample.user, encoding="utf-8"
    )

    mean_chars = float(np.mean(prompt_chars)) if prompt_chars else 0.0
    est_input = mean_chars / CHARS_PER_TOKEN
    summary: dict[str, Any] = {
        "corpus": {
            "assessments": len(assessments),
            "reference_drafts_built": len(frame),
            "skipped_no_deteriorating_dimension_or_score": skipped,
        },
        "false_positives": {
            "note": (
                "A reference draft is grounded by construction and deliberately rounds a"
                " stored percentile, quotes a clause rather than a whole sentence, and names"
                " a fiscal period that exists only as text. Any rejection here is the"
                " validator failing on a correct draft."
            ),
            "reference_drafts_rejected": int((~frame["reference_accepted"]).sum()),
            "false_positive_rate": round(float((~frame["reference_accepted"]).mean()), 4),
            "codes_seen": sorted(
                {
                    code
                    for row in frame["reference_findings"]
                    if row
                    for code in str(row).split(", ")
                }
            ),
        },
        "detection": {
            name: {
                "applicable": counts["applicable"],
                "not_applicable": counts["not_applicable"],
                "detected": counts["detected"],
                "detected_as_flag_only": counts.get("detected_as_flag", 0),
                "detection_rate": (
                    round(counts["detected"] / counts["applicable"], 4)
                    if counts["applicable"]
                    else None
                ),
                "verdict_correct_rate": (
                    round(counts["verdict_correct"] / counts["applicable"], 4)
                    if counts["applicable"]
                    else None
                ),
            }
            for name, counts in detection.items()
        },
        "precision_rule_sensitivity": {
            "note": (
                "A stated number is perturbed by k units in the last place it was written."
                " Under half a unit is rounding and must pass; over it is a different number"
                " and must fail."
            ),
            "n": sweep_total,
            "outcomes": {key: round(value / sweep_total, 4) for key, value in sorted(sweep.items())}
            if sweep_total
            else {},
        },
        "cost": {
            "note": (
                "No tokenizer offline: prompt size is measured in characters and converted at"
                f" {CHARS_PER_TOKEN} chars/token. A live run replaces this with"
                " usage.input_tokens."
            ),
            "mean_prompt_chars": round(mean_chars, 1),
            "estimated_input_tokens": round(est_input),
            "estimated_cost_per_assessment_usd": round(
                est_input / 1e6 * INPUT_PRICE_PER_MTOK + 1200 / 1e6 * OUTPUT_PRICE_PER_MTOK, 5
            ),
            "api_calls_per_assessment": 1,
        },
    }

    (OUT_DIR / "phase12_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
