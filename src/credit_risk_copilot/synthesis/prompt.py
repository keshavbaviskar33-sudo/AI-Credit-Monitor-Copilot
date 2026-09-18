"""Rendering an assessment into the one prompt the model gets.

FR-16 allows exactly one grounded call, so everything the draft may rest on
has to be in this prompt and nothing else may be. Two properties follow and
both are enforced here rather than requested of the model.

**The prompt is deterministic.** Same assessment, same bytes -- no timestamps,
no iteration order that depends on a dict's insertion history, no "generated
at". A non-deterministic prompt cannot be cached, cannot be diffed when a
draft changes, and cannot be re-run to reproduce a stored draft, which Phase
13 needs.

**The instructions are separate from the evidence.** `SynthesisRequest`
keeps the stable half (rules, schema, vocabulary) apart from the volatile half
(one company's evidence), because prompt caching is a prefix match and a
provider can only cache a prefix that is actually stable. Where the breakpoint
goes is each client's business; that the two halves are separable is this
module's.

## What the model is told it may not do

The system prompt states the same refusals the validator enforces. That is
belt and braces on purpose: the instruction makes a compliant draft the likely
outcome, and the validator makes a non-compliant one a detected one. Neither
substitutes for the other -- an instruction is not a guarantee, and a
validator that only ever rejects is a bad product.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from credit_risk_copilot.assessment.models import Assessment, EvidenceItem

#: The JSON Schema the response is constrained to. Passed as
#: `output_config.format`, so the model cannot return prose, a code fence or a
#: differently shaped object -- the parse either succeeds or the call failed,
#: and there is no salvage path that guesses at malformed output.
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["finding"]},
                "text": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["kind", "text", "evidence_ids"],
            "additionalProperties": False,
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["finding", "disagreement", "limitation", "check"],
                    },
                    "text": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "quote": {"type": ["string", "null"]},
                    "dimension": {"type": ["string", "null"]},
                },
                "required": ["kind", "text", "evidence_ids", "quote", "dimension"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "claims"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are drafting a credit-monitoring note for a qualified credit analyst who \
will review, edit or reject it. You are not making a credit decision and the \
analyst is not obliged to agree with you.

You will be given an EVIDENCE PACK: a list of facts, each with an identifier \
of the form EV-XX-xxxxxxxx, drawn from four independent analytical layers over \
one company's filings as of one date. You will also be given the \
DISAGREEMENTS and AGREEMENTS those layers produced, and a note of any layer \
that did not run.

RULES

1. Every claim you write must cite at least one evidence ID, in its \
`evidence_ids` field. A `check` claim -- a next action for the analyst -- may \
cite nothing.
2. You may only state numbers that appear in the evidence you cite for that \
claim. Do not compute new figures, do not convert units, do not average, do \
not annualise. If a figure you want is not in the evidence, do not write it.
3. If you present a quotation from the filing, put it in the claim's `quote` \
field and copy it character for character from a narrative evidence item you \
cite. Never paraphrase inside a quotation.
4. If the assessment lists any disagreements, write at least one claim of kind \
`disagreement` describing one. Do not resolve it -- say what disagrees and \
what a reader should check.
5. If any layer did not run, write a claim of kind `limitation` saying so. An \
absent layer is not a quiet one.
6. Never state a probability of default, a likelihood of bankruptcy, a credit \
rating, or a lend/decline recommendation. The model score is a position in a \
monitored ranking, not a probability. Say "ranks in the top N% of the \
monitored population", never "N% chance of default".
7. Write plainly. One assertion per claim. Prefer the evidence's own wording \
to a synonym.

You are drafting for review, not publishing a verdict."""


def _render_item(item: EvidenceItem) -> str:
    header = f"{item.evidence_id} [{item.layer.value}/{item.kind.value}"
    if item.dimension:
        header += f"/{item.dimension}"
    header += f"] concern={item.concern.value}"
    lines = [header, f"  {item.summary}"]
    if item.quote:
        lines.append(f'  verbatim: "{item.quote}"')
    return "\n".join(lines)


def _render_findings(assessment: Assessment) -> list[str]:
    lines: list[str] = []
    if assessment.contradictions:
        lines.append("DISAGREEMENTS")
        for finding in assessment.contradictions:
            lines.append(
                f"- {finding.code.value}"
                + (f" ({finding.dimension})" if finding.dimension else "")
                + f": {finding.explanation}"
            )
            lines.append(f"  sides: {', '.join(finding.cited) or 'none cited'}")
            lines.append(f"  to check: {finding.resolution_hint}")
    if assessment.corroborations:
        lines.append("")
        lines.append("AGREEMENTS")
        for finding in assessment.corroborations:
            lines.append(
                f"- {finding.code.value}"
                + (f" ({finding.dimension})" if finding.dimension else "")
                + f": {finding.explanation}"
            )
            lines.append(f"  supported by: {', '.join(finding.supporting)}")
    return lines


def evidence_pack(assessment: Assessment) -> str:
    """The per-company half of the prompt, rendered deterministically.

    Evidence is ordered by ID rather than by registration, so two runs of the
    same assessment produce byte-identical text even if a registrar's ordering
    changes -- the ID is content-derived, so sorting by it is stable in a way
    sorting by layer or by dimension is not.
    """
    ordered: Sequence[EvidenceItem] = sorted(assessment.evidence, key=lambda i: i.evidence_id)
    lines = [
        f"COMPANY: {assessment.company} (CIK {assessment.cik})",
        f"AS OF: {assessment.as_of.isoformat()}"
        + (f" | fiscal period {assessment.period_label}" if assessment.period_label else ""),
        "",
        f"EVIDENCE PACK ({len(ordered)} items)",
    ]
    lines.extend(_render_item(item) for item in ordered)

    if assessment.layers_absent:
        lines.append("")
        lines.append("LAYERS THAT DID NOT RUN")
        lines.extend(
            f"- {absence.layer.value}: {absence.reason}" for absence in assessment.layers_absent
        )

    findings = _render_findings(assessment)
    if findings:
        lines.append("")
        lines.extend(findings)

    lines.append("")
    lines.append("Draft the monitoring note for this company, following the rules you were given.")
    return "\n".join(lines)


@dataclass(frozen=True)
class SynthesisRequest:
    """One assessment's prompt, in nobody's wire format.

    The first version of this module returned an Anthropic Messages dict, on
    the reasoning that there was one provider and an abstraction over one
    implementation is fitted to it. Adding a second provider showed what that
    cost: the *prompt* -- the instructions, the evidence, the output contract
    -- is the thing this project owns and versions, and burying it in one
    vendor's envelope made a stored draft's fingerprint vendor-flavoured
    forever.

    So the three things that are ours live here, and each client renders them
    into its own request. `model` is deliberately absent: which model runs a
    prompt is a property of the client, not of the prompt, and including it
    would make two providers' fingerprints differ for an identical prompt.
    """

    system: str
    user: str
    #: JSON Schema the response must satisfy. Both providers accept standard
    #: JSON Schema; neither is allowed to return prose.
    schema: dict
    max_tokens: int = 8000


def build_request(assessment: Assessment, *, max_tokens: int = 8000) -> SynthesisRequest:
    """The prompt for one assessment, built but not issued.

    Returned rather than sent so it can be inspected, diffed and tested
    without an API key -- and so the only code that talks to a provider stays
    in `client.py`.
    """
    return SynthesisRequest(
        system=SYSTEM_PROMPT,
        user=evidence_pack(assessment),
        schema=RESPONSE_SCHEMA,
        max_tokens=max_tokens,
    )


def request_fingerprint(assessment: Assessment) -> str:
    """A stable digest of the prompt an assessment produces.

    Phase 13 stores a draft immutably; this is what lets a later reader
    confirm the stored draft came from the prompt the stored assessment
    implies, without keeping a second copy of the prompt. Provider-independent,
    so the same assessment fingerprints identically whichever model drafted it
    -- which is what makes two providers' drafts comparable at all.
    """
    from hashlib import blake2s

    request = build_request(assessment)
    payload = json.dumps(
        {
            "system": request.system,
            "user": request.user,
            "schema": request.schema,
            "max_tokens": request.max_tokens,
        },
        sort_keys=True,
    )
    return blake2s(payload.encode("utf-8"), digest_size=8).hexdigest()
