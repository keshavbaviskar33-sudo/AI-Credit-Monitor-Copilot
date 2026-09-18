"""The prompt, the single call, and what comes back."""

from __future__ import annotations

import json

import pytest

from credit_risk_copilot.assessment.models import EvidenceKind
from credit_risk_copilot.synthesis.client import ScriptedClient, SynthesisError, parse_draft
from credit_risk_copilot.synthesis.engine import synthesize
from credit_risk_copilot.synthesis.prompt import (
    RESPONSE_SCHEMA,
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
    assert request_fingerprint(assessment, model="m") == request_fingerprint(assessment, model="m")


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


def test_the_stable_instructions_carry_the_cache_breakpoint():
    request = build_request(build_assessment(), model="claude-opus-5")
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Volatile content must sit after the breakpoint or the prefix changes
    # every call and nothing is ever cached.
    assert "TEST CO" not in request["system"][0]["text"]
    assert "TEST CO" in request["messages"][0]["content"]


def test_the_response_is_constrained_to_the_draft_schema():
    request = build_request(build_assessment(), model="claude-opus-5")
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"] == RESPONSE_SCHEMA
    assert RESPONSE_SCHEMA["additionalProperties"] is False


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
