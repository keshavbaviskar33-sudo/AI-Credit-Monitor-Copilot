"""The prompt, the single call, and what comes back."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from credit_risk_copilot.assessment.models import EvidenceKind
from credit_risk_copilot.synthesis import prompt as prompt_module
from credit_risk_copilot.synthesis.client import (
    ScriptedClient,
    SynthesisError,
    parse_draft,
    render_anthropic,
)
from credit_risk_copilot.synthesis.engine import synthesize
from credit_risk_copilot.synthesis.prompt import (
    RESPONSE_SCHEMA,
    SynthesisRequest,
    build_request,
    evidence_pack,
    request_fingerprint,
)
from credit_risk_copilot.synthesis.schema import Claim, ClaimKind, DraftSynthesis

from .test_synthesis_validator import build_assessment, good_draft


def test_the_prompt_is_deterministic():
    """A prompt that varies between runs cannot be cached, diffed, or used to
    reproduce a stored draft."""
    assessment = build_assessment()
    assert evidence_pack(assessment) == evidence_pack(assessment)
    assert request_fingerprint(assessment) == request_fingerprint(assessment)


def test_every_evidence_item_reaches_the_prompt():
    """FR-16 allows one call, so anything not in this prompt can never be
    cited -- an item silently omitted here is an item the draft cannot use."""
    assessment = build_assessment()
    pack = evidence_pack(assessment)
    for item in assessment.evidence:
        assert item.evidence_id in pack


def test_verbatim_quotes_reach_the_prompt():
    assessment = build_assessment()
    pack = evidence_pack(assessment)
    for item in assessment.of_kind(EvidenceKind.NARRATIVE_SIGNAL):
        assert item.quote is not None
        assert item.quote in pack


def test_disagreements_and_absences_are_in_the_prompt():
    """The model cannot describe what it was not shown, and the validator
    rejects a draft that omits either."""
    assessment = build_assessment(with_model=False)
    pack = evidence_pack(assessment)
    assert "LAYERS THAT DID NOT RUN" in pack
    assert "company outside training range" in pack
    with_findings = build_assessment()
    assert "DISAGREEMENTS" in evidence_pack(with_findings)


def test_the_prompt_separates_the_stable_half_from_the_volatile_half():
    """A provider can only cache a prefix that is actually stable."""
    request = build_request(build_assessment())
    assert "TEST CO" not in request.system
    assert "TEST CO" in request.user


def test_the_prompt_is_in_no_providers_wire_format():
    """The instructions, the evidence and the output contract are what this
    project owns. Burying them in one vendor's envelope, as the first version
    did, made a stored draft's fingerprint vendor-flavoured forever."""
    request = build_request(build_assessment())
    assert isinstance(request, SynthesisRequest)
    assert not hasattr(request, "model")
    assert request.schema is RESPONSE_SCHEMA
    assert RESPONSE_SCHEMA["additionalProperties"] is False


def test_the_fingerprint_does_not_depend_on_the_provider():
    """Two models drafting the same assessment must fingerprint identically, or
    their drafts cannot be compared."""
    assessment = build_assessment()
    assert request_fingerprint(assessment) == request_fingerprint(assessment)
    assert len(request_fingerprint(assessment)) == 16


def test_the_anthropic_renderer_places_the_cache_breakpoint_and_the_schema():
    request = build_request(build_assessment())
    rendered = render_anthropic(request, "claude-opus-5")
    assert rendered["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert rendered["system"][0]["text"] == request.system
    assert rendered["messages"][0]["content"] == request.user
    assert rendered["output_config"]["format"]["type"] == "json_schema"
    assert rendered["output_config"]["format"]["schema"] == request.schema


def test_synthesize_makes_exactly_one_call_and_validates_the_result():
    assessment = build_assessment()
    client = ScriptedClient({"TEST CO": good_draft(assessment)})
    result = synthesize(assessment, client)
    assert len(client.requests) == 1
    assert result.api_calls == 1
    assert result.validation.accepted


def test_a_rejected_draft_is_returned_rather_than_retried():
    """Retrying inside `synthesize` would hide the rejection rate, which is the
    number this phase exists to measure."""
    assessment = build_assessment()
    bad = DraftSynthesis(
        headline=Claim(kind=ClaimKind.FINDING, text="Ranks high.", evidence_ids=("EV-MS-00000000",))
    )
    client = ScriptedClient({"TEST CO": bad})
    result = synthesize(assessment, client)
    assert len(client.requests) == 1
    assert not result.validation.accepted


def test_a_malformed_response_fails_loudly():
    """No best-effort salvage: a partially recovered draft would be validated,
    possibly accepted, and stored as though the model had written it."""
    with pytest.raises(SynthesisError, match="not valid JSON"):
        parse_draft("{not json")
    with pytest.raises(SynthesisError, match="did not match the draft schema"):
        parse_draft(json.dumps({"headline": {"text": "no kind field"}}))


def test_both_providers_satisfy_one_protocol():
    """Neither client may leak its wire format into the rest of the package.

    Checked structurally rather than by instantiation: constructing either one
    requires its SDK, and the point of the seam is that everything above it
    works without either.
    """
    from credit_risk_copilot.synthesis.client import (
        AnthropicSynthesisClient,
        GeminiSynthesisClient,
    )

    for client in (AnthropicSynthesisClient, GeminiSynthesisClient):
        assert hasattr(client, "complete")
        assert isinstance(client.model, property)

    # The prompt module must not *import* either SDK. Checked on the import
    # statements rather than on the word: the module's docstring names
    # Anthropic when explaining why the request stopped being an Anthropic
    # dict, and a substring check would forbid the explanation along with the
    # dependency.
    tree = ast.parse(Path(prompt_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "anthropic" not in imported
    assert "google" not in imported
