"""The one place this project talks to a language model.

Everything else in `synthesis/` -- the schema, the prompt, the validator --
works on dicts and pydantic objects and never imports a provider SDK. That is
not provider neutrality for its own sake: it is what lets the validator, the
phase's actual deliverable, be measured without an API key, a network, or a
model whose behaviour on the day would determine the result.

Three implementations of one protocol:

- `AnthropicSynthesisClient` -- the shipped path. One `messages.create` call,
  structured output constrained by JSON Schema, prompt caching on the stable
  system prefix.
- `ScriptedClient` -- returns a draft prepared in advance. What the tests and
  the fault-injection measurement run on.
- `RecordingClient` -- wraps another client and keeps the raw response, so a
  live run can be replayed later without spending anything.

`anthropic` is an optional dependency and is imported inside the constructor.
A project whose test suite cannot run without a paid API key is a project
whose test suite stops being run.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from credit_risk_copilot.synthesis.schema import DraftSynthesis


class SynthesisError(RuntimeError):
    """The call did not produce a parseable draft."""


class SynthesisClient(Protocol):
    """One request in, one draft plus usage out."""

    @property
    def model(self) -> str: ...

    def complete(self, request: dict) -> tuple[DraftSynthesis, dict[str, Any]]: ...


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

    def complete(self, request: dict) -> tuple[DraftSynthesis, dict[str, Any]]:
        response = self._client.messages.create(**request)
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
        self.requests: list[dict] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, request: dict) -> tuple[DraftSynthesis, dict[str, Any]]:
        self.requests.append(request)
        pack = request["messages"][0]["content"]
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
        self.recorded: list[tuple[dict, DraftSynthesis, dict[str, Any]]] = []

    @property
    def model(self) -> str:
        return self._inner.model

    def complete(self, request: dict) -> tuple[DraftSynthesis, dict[str, Any]]:
        draft, usage = self._inner.complete(request)
        self.recorded.append((request, draft, usage))
        return draft, usage
