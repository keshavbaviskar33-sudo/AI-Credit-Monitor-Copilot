"""The synthesis draft, and what code is allowed to say about it.

Phase 12 makes one LLM call over a Phase 11 `Assessment` and gets back a
draft. The draft is not the deliverable -- the **verdict on the draft** is.
FR-17 requires code, not the model, to detect a claim that cites evidence
which does not exist or states a number that was never measured, and a schema
that cannot express that verdict cannot enforce it.

## Why the draft is a list of claims rather than prose

A paragraph cannot be validated. "Leverage deteriorated sharply while the
filer affirmed covenant compliance, and the model ranks the company in the top
2%" contains three assertions resting on different evidence, and a citation
attached to the paragraph attaches to none of them in particular. So the unit
is a `Claim`: one assertion, its own citations, checked on its own. The
rendering layer joins them; the validator never has to split them.

## Two kinds of failure, kept apart

A number that appears nowhere in the assessment is **fabricated**. A number
that is real but attached to a claim citing different evidence is
**mis-cited**. Both are wrong and they are not the same wrong: the first means
the model invented a measurement, the second means it attached a true one to
the wrong sentence. `Severity` keeps them apart so a reviewer can tell a
hallucination from a filing error, and so the reject rule can be strict about
the first without being unusable about the second.

## No score about the draft

There is no "groundedness score" here, for the reason this project has given
four times (D-010, D-022, D-033, D-036): a number between 0 and 1 would be
read instead of the findings. `ValidationReport.verdict` is a decision, and
`findings` is the list; nothing summarises them into a digit.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ClaimKind(str, Enum):
    """What role a claim plays in the draft.

    Kinds are required rather than inferred, because the completeness checks
    need to know whether the draft *attempted* to describe a disagreement. A
    draft with no `DISAGREEMENT` claim and an assessment with three
    contradictions is a specific, detectable failure; a draft whose prose
    happens to mention tension is not something code can recognise.
    """

    #: An observation about the company drawn from one or more layers.
    FINDING = "finding"
    #: A disagreement between layers, mirroring a Phase 11 contradiction.
    DISAGREEMENT = "disagreement"
    #: Something the assessment could not establish -- a missing layer, an
    #: unlocated section, a dimension with no conclusive trend.
    LIMITATION = "limitation"
    #: A next action for the analyst. The only kind allowed to be forward
    #: looking, and still not allowed to predict an outcome.
    CHECK = "check"


class FailureCode(str, Enum):
    """Machine-readable grounding failures (FR-17)."""

    #: The claim cites an evidence ID this assessment does not contain.
    UNRESOLVED_CITATION = "unresolved_citation"
    #: The claim cites nothing at all.
    UNCITED_CLAIM = "uncited_claim"
    #: The claim states a number that appears nowhere in the assessment.
    UNGROUNDED_NUMBER = "ungrounded_number"
    #: The number is real but is not in the evidence this claim cites.
    MISCITED_NUMBER = "miscited_number"
    #: The claim presents quoted text that is not verbatim in a cited
    #: narrative evidence item.
    NON_VERBATIM_QUOTE = "non_verbatim_quote"
    #: The draft asserts a probability of default, a rating or a credit
    #: decision -- the output shape D-010 exists to prevent.
    FORBIDDEN_CONCLUSION = "forbidden_conclusion"
    #: The assessment carries contradictions and the draft describes none.
    OMITTED_CONTRADICTION = "omitted_contradiction"
    #: A layer did not run and the draft does not say so, so a reader cannot
    #: tell silence from absence.
    OMITTED_LAYER_ABSENCE = "omitted_layer_absence"


class Severity(str, Enum):
    """Whether a failure kills the draft or annotates it."""

    #: The draft may not be shown to an analyst as-is.
    REJECT = "reject"
    #: The draft is shown with the finding attached. Reserved for failures
    #: where the *facts* are real and the attachment is wrong, which a
    #: reviewer can fix without a regeneration.
    FLAG = "flag"


#: Which failures reject. Fabrication and omission both reject: a draft that
#: invents a figure and a draft that hides a disagreement are equally unusable,
#: and D-038's consequence names the second explicitly.
REJECTING: frozenset[FailureCode] = frozenset(
    {
        FailureCode.UNRESOLVED_CITATION,
        FailureCode.UNCITED_CLAIM,
        FailureCode.UNGROUNDED_NUMBER,
        FailureCode.NON_VERBATIM_QUOTE,
        FailureCode.FORBIDDEN_CONCLUSION,
        FailureCode.OMITTED_CONTRADICTION,
        FailureCode.OMITTED_LAYER_ABSENCE,
    }
)


class Claim(BaseModel):
    """One assertion, with the evidence it rests on."""

    model_config = ConfigDict(frozen=True)

    kind: ClaimKind
    #: One sentence. Every number in it is checked against `evidence_ids`.
    text: str
    #: Phase 11 evidence IDs. Never a restatement of the evidence itself.
    evidence_ids: tuple[str, ...] = ()
    #: Verbatim source text the claim presents as a quotation, if any. Checked
    #: character-for-character against the cited narrative evidence.
    quote: str | None = None
    dimension: str | None = None


class DraftSynthesis(BaseModel):
    """What the model returned, before anything has been checked.

    Deliberately named a *draft*: D-003 gives every final judgement to the
    analyst, and Phase 13 stores this object immutably alongside whatever the
    analyst does to it.
    """

    model_config = ConfigDict(frozen=True)

    #: One sentence stating the company's position. Validated like any claim:
    #: it carries its own citations.
    headline: Claim
    claims: tuple[Claim, ...] = ()

    @property
    def all_claims(self) -> tuple[Claim, ...]:
        return (self.headline, *self.claims)

    def of_kind(self, kind: ClaimKind) -> tuple[Claim, ...]:
        return tuple(claim for claim in self.all_claims if claim.kind is kind)


class GroundingFinding(BaseModel):
    """One reason a draft is not fully supported by its evidence."""

    model_config = ConfigDict(frozen=True)

    code: FailureCode
    severity: Severity
    #: Index into `DraftSynthesis.all_claims`; `None` for whole-draft failures
    #: such as an omitted contradiction.
    claim_index: int | None = None
    #: The offending fragment -- the fabricated ID, the unsupported literal,
    #: the quoted text that is not in the filing.
    subject: str | None = None
    detail: str


class ValidationReport(BaseModel):
    """The verdict, and every finding behind it."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    findings: tuple[GroundingFinding, ...] = ()
    #: Counts that make a batch run summarisable without re-walking findings.
    claims_checked: int = Field(default=0, ge=0)
    citations_checked: int = Field(default=0, ge=0)
    numbers_checked: int = Field(default=0, ge=0)

    @property
    def rejections(self) -> tuple[GroundingFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.REJECT)

    @property
    def flags(self) -> tuple[GroundingFinding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.FLAG)

    def codes(self) -> frozenset[FailureCode]:
        return frozenset(finding.code for finding in self.findings)


class SynthesisResult(BaseModel):
    """A draft, its verdict, and what the call cost.

    Usage is recorded on the result rather than logged, because the cost NFR
    is one call per assessment and a claim about cost that lives only in a log
    line cannot be asserted in a test.
    """

    model_config = ConfigDict(frozen=True)

    cik: int
    company: str
    as_of: str
    draft: DraftSynthesis
    validation: ValidationReport
    model: str
    #: Exactly one on the shipped path. Recorded so a regression that adds a
    #: second call is visible rather than invisible.
    api_calls: int = 1
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
