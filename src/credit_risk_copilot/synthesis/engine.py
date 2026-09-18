"""One assessment in, one validated draft out (FR-16, FR-17).

The whole phase is four lines of control flow, and that is the point: build
the prompt, make exactly one call, validate the result, return both. Anything
cleverer -- a repair loop, a second call to fix a rejected draft, a fallback
to a smaller model -- would break the cost NFR and, worse, would let a draft
reach an analyst *because* a model was asked twice rather than because the
evidence supported it.

## Why a rejected draft is returned rather than retried

`synthesize` returns the draft and the verdict together even when the verdict
is a rejection. Retrying inside this function would hide the rejection rate,
which is the number Phase 12 exists to measure and the number Phase 13's
reviewer needs in order to know how much to trust what they are reading. A
caller that wants to regenerate can call again and will see it did.
"""

from __future__ import annotations

from credit_risk_copilot.assessment.models import Assessment
from credit_risk_copilot.synthesis.client import SynthesisClient
from credit_risk_copilot.synthesis.prompt import build_request
from credit_risk_copilot.synthesis.schema import SynthesisResult
from credit_risk_copilot.synthesis.validator import validate


def synthesize(
    assessment: Assessment, client: SynthesisClient, *, max_tokens: int = 8000
) -> SynthesisResult:
    """Draft a monitoring note for one assessment and check it against its evidence."""
    request = build_request(assessment, max_tokens=max_tokens)
    draft, usage = client.complete(request)
    return SynthesisResult(
        cik=assessment.cik,
        company=assessment.company,
        as_of=assessment.as_of.isoformat(),
        draft=draft,
        validation=validate(draft, assessment),
        model=client.model,
        api_calls=1,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cache_read_tokens=usage.get("cache_read_tokens"),
    )
