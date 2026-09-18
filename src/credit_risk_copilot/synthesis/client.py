"""The one place this project talks to a language model.

Everything else in `synthesis/` -- the schema, the prompt, the validator --
works on dicts and pydantic objects and never imports a provider SDK. That is
not provider neutrality for its own sake: it is what lets the validator, the
phase's actual deliverable, be measured without an API key, a network, or a
model whose behaviour on the day would determine the result.

Four implementations of one protocol, each taking the same provider-neutral
`SynthesisRequest` and rendering it into its own wire format:

- `AnthropicSynthesisClient` -- one `messages.create` call, JSON-Schema
  structured output, a cache breakpoint on the stable system prefix.
- `GeminiSynthesisClient` -- one `generate_content` call, the same JSON Schema
  via `response_json_schema`, the same system text via `system_instruction`.
- `ScriptedClient` -- returns a draft prepared in advance. What the tests and
  the fault-injection measurement run on.
- `RecordingClient` -- wraps another client and keeps every draft, so a live
  run can be re-analysed after the validator changes without paying again.

**Why two providers instead of an abstraction over none.** The second client
was added when a key for a different provider turned up, and it earned its
keep immediately: it forced the prompt out of one vendor's envelope
(`prompt.SynthesisRequest`), which is what makes a stored draft's fingerprint
provider-independent and two models' drafts comparable on the same assessment.
An abstraction written before the second implementation would have been fitted
to the first one anyway.

Both SDKs are optional dependencies imported inside their constructors. A
project whose test suite cannot run without a paid API key is a project whose
test suite stops being run.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from credit_risk_copilot.synthesis.prompt import SynthesisRequest
from credit_risk_copilot.synthesis.schema import DraftSynthesis


class SynthesisError(RuntimeError):
    """The call did not produce a parseable draft."""


class SynthesisClient(Protocol):
    """One request in, one draft plus usage out."""

    @property
    def model(self) -> str: ...

    def complete(self, request: SynthesisRequest) -> tuple[DraftSynthesis, dict[str, Any]]: ...


def parse_draft(payload: str) -> DraftSynthesis:
    """Turn the model's JSON into a `DraftSynthesis`, or fail loudly.

    `output_config.format` guarantees valid JSON matching the schema, so a
    failure here is a real breakage -- a provider change, a truncated response
    -- and is raised rather than repaired. There is deliberately no
    best-effort salvage: a partially recovered draft would be validated,
    possibly accepted, and stored as though the model had written it.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SynthesisError(f"response was not valid JSON: {error}") from error
    try:
        return DraftSynthesis.model_validate(data)
    except Exception as error:  # pydantic ValidationError and friends
        raise SynthesisError(f"response did not match the draft schema: {error}") from error


def render_anthropic(request: SynthesisRequest, model: str) -> dict:
    """The Messages API request a prompt becomes.

    A module-level function rather than a client method because it is a pure
    function of the prompt and the model name, and a wire format that can only
    be inspected by constructing a client is a wire format that only gets
    tested when the SDK is installed.

    The cache breakpoint sits on the stable instructions, which is the prefix
    `tools` -> `system` -> `messages` makes cacheable. Whether that prefix
    clears the model's minimum cacheable length is not asserted here -- it is
    read back from `usage.cache_read_input_tokens`.
    """
    return {
        "model": model,
        "max_tokens": request.max_tokens,
        "system": [
            {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": request.user}],
        "output_config": {"format": {"type": "json_schema", "schema": request.schema}},
    }


class AnthropicSynthesisClient:
    """One grounded call to Claude (FR-16).

    `max_retries=0` on the client: the SDK's automatic retries would turn one
    logical call into several billed ones, and the NFR this phase is written
    against is one call per assessment. A rate-limit failure is surfaced to the
    caller, which can decide, rather than absorbed here where the cost would be
    invisible.
    """

    def __init__(self, *, model: str = "claude-opus-5", api_key: str | None = None) -> None:
        try:
            import anthropic
        except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
            raise SynthesisError(
                "the `anthropic` package is required for live synthesis;"
                " install the project's `llm` extra"
            ) from error
        self._client = anthropic.Anthropic(
            max_retries=0, **({"api_key": api_key} if api_key else {})
        )
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: SynthesisRequest) -> tuple[DraftSynthesis, dict[str, Any]]:
        response = self._client.messages.create(**render_anthropic(request, self._model))
        # Guard before reading content: a refusal returns HTTP 200 with no
        # usable text, and indexing content would raise something unrelated to
        # what actually happened.
        if response.stop_reason == "refusal":
            raise SynthesisError(
                "the model declined this request"
                + (f" ({response.stop_details.category})" if response.stop_details else "")
            )
        if response.stop_reason == "max_tokens":
            raise SynthesisError("the response hit max_tokens and the draft is truncated")
        text = next((block.text for block in response.content if block.type == "text"), None)
        if text is None:
            raise SynthesisError("the response contained no text block")
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", None),
        }
        return parse_draft(text), usage


class ScriptedClient:
    """Returns drafts prepared in advance, keyed by company.

    The test and measurement path. It takes `DraftSynthesis` objects rather
    than JSON so a fault-injection case can be expressed as an object mutation
    -- flip a digit, drop a citation -- instead of as hand-edited JSON that
    might not parse for a reason unrelated to the fault being tested.
    """

    def __init__(self, drafts: dict[str, DraftSynthesis], *, model: str = "scripted") -> None:
        self._drafts = drafts
        self._model = model
        self.requests: list[SynthesisRequest] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: SynthesisRequest) -> tuple[DraftSynthesis, dict[str, Any]]:
        self.requests.append(request)
        pack = request.user
        for key, draft in self._drafts.items():
            if key in pack:
                return draft, {"input_tokens": None, "output_tokens": None}
        raise SynthesisError(f"no scripted draft matches this request ({len(self._drafts)} known)")


class RecordingClient:
    """Wraps a client and keeps every draft it produced.

    A live run is the only way to learn what a real model does with this
    prompt, and it costs money each time. Recording makes the second analysis
    of the same run free, and makes a stored draft re-checkable after the
    validator changes.
    """

    def __init__(self, inner: SynthesisClient) -> None:
        self._inner = inner
        self.recorded: list[tuple[SynthesisRequest, DraftSynthesis, dict[str, Any]]] = []

    @property
    def model(self) -> str:
        return self._inner.model

    def complete(self, request: SynthesisRequest) -> tuple[DraftSynthesis, dict[str, Any]]:
        draft, usage = self._inner.complete(request)
        self.recorded.append((request, draft, usage))
        return draft, usage


class GeminiSynthesisClient:
    """One grounded call to Gemini (FR-16), same contract as the Anthropic path.

    The second provider exists because a key for one turned up, and keeping it
    means two independent models can be measured on the *same* assessment with
    the *same* prompt and judged by the *same* validator -- which is a stronger
    statement about the grounding layer than either model alone can make.

    Three differences from the Anthropic client, all of them wire-level:

    - the system text goes in `system_instruction` rather than a `system`
      block, so there is no cache breakpoint to place; Gemini's implicit
      caching decides for itself, and `cached_content_token_count` is read back
      rather than assumed;
    - the schema goes in `response_json_schema` with an explicit JSON mime
      type, which is the same guarantee `output_config.format` gives -- the
      parse either succeeds or the call failed;
    - the finish reason is named `finish_reason` and its safety stop is `SAFETY`
      rather than a `refusal` stop reason.

    The default model is a flash tier rather than a pro one, which is a
    deployment fact and not a quality judgement: the pro models return
    `RESOURCE_EXHAUSTED` with a free-tier limit of zero, so the default is the
    most capable model the credential can actually reach. Pass `model=` to
    override on a paid key.

    The default model is a flash tier rather than a pro one, which is a
    deployment fact and not a quality judgement: on a free credential the pro
    models return `RESOURCE_EXHAUSTED` with a stated limit of zero, so the
    default is the most capable model an ordinary key can actually reach.
    Pass `model=` to override on a paid key.

    `truststore` is injected before the client is built. The project already
    depends on it for SEC access behind a corporate TLS interceptor, and
    without it the SDK's bundled certificate store rejects the connection --
    a failure that looks like an auth problem and is not.
    """

    def __init__(self, *, model: str = "gemini-3.6-flash", api_key: str | None = None) -> None:
        try:
            import truststore
            from google import genai
        except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
            raise SynthesisError(
                "the `google-genai` package is required for Gemini synthesis;"
                " install the project's `llm` extra"
            ) from error
        truststore.inject_into_ssl()
        self._genai = genai
        self._client = genai.Client(**({"api_key": api_key} if api_key else {}))
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def render(self, request: SynthesisRequest):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=request.system,
            max_output_tokens=request.max_tokens,
            response_mime_type="application/json",
            response_json_schema=request.schema,
        )

    def complete(self, request: SynthesisRequest) -> tuple[DraftSynthesis, dict[str, Any]]:
        from google.genai import errors

        try:
            response = self._client.models.generate_content(
                model=self._model, contents=request.user, config=self.render(request)
            )
        except errors.APIError as error:
            # Translated rather than propagated, so a quota refusal on one
            # company is one recorded failure instead of a dead batch. The
            # caller still sees it and still does not retry -- D-042 -- but a
            # provider's exception type is not something the rest of this
            # project should have to know about.
            raise SynthesisError(f"{type(error).__name__}: {error}") from error
        # Guard before reading text, for the same reason the Anthropic client
        # does: a safety stop or a truncation returns a successful HTTP
        # response with no usable draft, and reading `.text` first would raise
        # something unrelated to what actually happened.
        candidates = response.candidates or []
        reason = str(getattr(candidates[0], "finish_reason", "")) if candidates else "NO_CANDIDATE"
        if "SAFETY" in reason or "BLOCK" in reason or "PROHIBITED" in reason:
            raise SynthesisError(f"the model declined this request ({reason})")
        if "MAX_TOKENS" in reason:
            raise SynthesisError("the response hit max_output_tokens and the draft is truncated")
        text = response.text
        if not text:
            raise SynthesisError(f"the response contained no text (finish_reason={reason})")

        usage = getattr(response, "usage_metadata", None)
        return parse_draft(text), {
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "cache_read_tokens": getattr(usage, "cached_content_token_count", None),
        }
