"""One grounded synthesis call, and the code that checks it (Phase 12).

Takes a Phase 11 `Assessment`, renders it into a single prompt, makes exactly
one LLM call constrained to a JSON schema, and validates every claim in the
result against the evidence it cites.

    result = synthesize(assessment, AnthropicSynthesisClient())
    result.validation.accepted        # FR-17: did the draft stay grounded?
    result.validation.findings        # every fabricated ID, number and quote

The draft is not the product -- the verdict on the draft is. The model is
allowed to write the sentences and is not trusted to have written true ones,
which is why `validator.py` is the largest module here and imports no provider
SDK at all.
"""

from credit_risk_copilot.synthesis.client import (
    AnthropicSynthesisClient,
    GeminiSynthesisClient,
    RecordingClient,
    ScriptedClient,
    SynthesisClient,
    SynthesisError,
    parse_draft,
    render_anthropic,
)
from credit_risk_copilot.synthesis.engine import synthesize
from credit_risk_copilot.synthesis.numbers import mentions, ungrounded
from credit_risk_copilot.synthesis.prompt import (
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    SynthesisRequest,
    build_request,
    evidence_pack,
    request_fingerprint,
)
from credit_risk_copilot.synthesis.schema import (
    Claim,
    ClaimKind,
    DraftSynthesis,
    FailureCode,
    GroundingFinding,
    Severity,
    SynthesisResult,
    ValidationReport,
)
from credit_risk_copilot.synthesis.validator import validate

__all__ = [
    "RESPONSE_SCHEMA",
    "SYSTEM_PROMPT",
    "AnthropicSynthesisClient",
    "Claim",
    "ClaimKind",
    "DraftSynthesis",
    "GeminiSynthesisClient",
    "FailureCode",
    "GroundingFinding",
    "RecordingClient",
    "ScriptedClient",
    "Severity",
    "SynthesisClient",
    "SynthesisError",
    "SynthesisRequest",
    "SynthesisResult",
    "ValidationReport",
    "build_request",
    "evidence_pack",
    "mentions",
    "parse_draft",
    "render_anthropic",
    "request_fingerprint",
    "synthesize",
    "ungrounded",
    "validate",
]
