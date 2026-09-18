"""Is the filer saying this happened, or saying it might?

This module is the reason the phase is worth doing. Keyword matching over a
10-K finds distress language in every filing ever written, because Item 1A's
job is to enumerate everything that could go wrong. Apple's risk factors
discuss default; Coca-Cola's discuss liquidity. Neither company is in trouble.

What distinguishes a filing that is *in* distress is the mood of the sentence:

    "There exists substantial doubt whether we will be able to
     continue as a going concern."                                 ASSERTED

    "If we are unable to refinance our indebtedness, we may be
     unable to continue as a going concern."                       HYPOTHETICAL

    "See Note 1 for further discussion of the Company's ability
     to continue as a going concern."                              CROSS_REFERENCE

    "No event of default has occurred under the Credit Facility."  NEGATED

Four classes, decided by inspectable cues rather than a classifier. There is no
labelled corpus to train one on, a classifier would not be explainable to an
analyst reading its output, and A-15 commits the project to rules first. The
measured cost and benefit of this gate is reported in
`docs/nlp_risk_signals.md` §5 -- it is the single largest determinant of the
layer's precision.

## The scope rule, and why it is not "cues before the trigger"

The intuitive rule is that a cue governs a trigger only when it precedes it:

    "If we breach a covenant, our lenders may accelerate."     -> hypothetical
    "We breached a covenant, and may seek an amendment."       -> asserted

Both contain "may"; only the first is governed by it. That rule was
implemented first and it is **wrong**, because it misses the construction
where the hypothetical's subject *is* the trigger:

    "Any downgrade of our credit ratings could increase our
     future borrowing costs."                                  -> hypothetical

The modal follows the trigger here, and a backward-only search finds nothing
before it but the word "any". Walmart's MD&A contains exactly this sentence
and it was read as an asserted downgrade.

The rule that works gives each cue class the scope its grammar actually has,
and lets *precedence* do the disambiguating that scope was being asked to do:

| Cue class | Scope | Why |
|---|---|---|
| Attached denial | the ~14 characters before the trigger | "no *event of default*" negates; a `not` further away may belong to a different clause, or be part of the trigger itself |
| Compliance denial, conditional, factual override | the clause before the trigger | these govern what follows them |
| Modal | the whole sentence | the modal governing a trigger in subject position comes after it |

The second example above is asserted because "we breached" precedes the
trigger, not because "may" follows it.

## Why "is there a negation nearby" cannot work

Whether a `not` denies the signal or *is* the signal depends on the trigger it
attaches to:

    "we were not in default"      -> denial (there was no default)
    "we were not in compliance"   -> the breach itself

Both contain "were not". The catalog's own pattern for a breach is
`not in compliance`, so in the second the `not` sits *inside* the trigger and
in the first it sits outside. Only adjacency tells those apart.
"""

from __future__ import annotations

import re

from credit_risk_copilot.nlp.models import Assertion

#: **Conditionals**, which subordinate everything that follows them and
#: therefore outrank a factual override. "If we are unable to refinance, we may
#: be unable to continue as a going concern" contains "we are", which reads as
#: a statement of fact in isolation and is not one here.
#:
#: Scanned in the backward window only, which is not a compromise but the
#: grammar: a conditional governs its consequent, so one that governs the
#: trigger precedes it. Scanning the whole sentence would misread "We were not
#: in compliance, and if our lenders accelerate..." as hypothetical.
_CONDITIONAL_CUES = (
    r"\bif\b",
    r"\bunless\b",
    r"\bshould we\b",
    r"\bshould the\b",
    r"\bwere we to\b",
    r"\bin the event\b",
    r"\bto the extent that\b",
    r"\bcan(?:not)? be (?:no )?assurance\b",
    # "We cannot provide assurance that ... a rating will not be lowered" --
    # the same hedge without the verb "be", and the source of a false
    # `CREDIT_RATING_DOWNGRADE` in the development sample.
    r"\bcan(?:not)? (?:provide|give|offer|assure)\b",
    r"\bany failure\b",
    r"\ba failure\b",
    r"\bfailure to\b",
    r"\brisk that\b",
)

#: **Modals**, the workhorses of risk-factor prose. Weaker than a conditional:
#: a stated fact outranks them, so these are tested after the factual
#: overrides. Scanned over the whole sentence, because the modal that governs a
#: trigger in subject position follows it ("Any downgrade of our credit ratings
#: could increase our borrowing costs").
_MODAL_CUES = (
    r"\bmay\b",
    r"\bmight\b",
    r"\bcould\b",
    r"\bwould\b",
    # "all reporting units **can** confront events that can lead to a goodwill
    # impairment charge" -- Pfizer's accounting-policy prose, which reads as an
    # asserted impairment without this.
    r"\bcan\b",
    r"\bwe expect\b",
    r"\bwe anticipate\b",
    r"\bis designed to\b",
    r"\bcould result\b",
    r"\bpotential(?:ly)?\b",
)

#: Pointers. These assert nothing -- they say where an assertion lives. Kept
#: separate from `HYPOTHETICAL` because the distinction is real: a cross
#: reference in Item 7 to a going-concern note means the note exists, which is
#: itself evidence, where a hypothetical means only that a lawyer was thorough.
_CROSS_REFERENCE_CUES = (
    r"\b(?:see|refer to|described in|discussed in|set forth in|included in|as defined in)\b"
    r"[^.]{0,60}\b(?:note|item|section|part|exhibit|schedule|discussion)\b",
    r"\bfor (?:further|additional|more) (?:discussion|information|detail)\b",
)

#: **Denials attached directly to the trigger**, checked only in the handful of
#: characters immediately before it: "**no** event of default", "**not** in
#: default", "**without** any material weakness".
#:
#: Adjacency is what makes this safe, and the reason is polarity. A general
#: "is there a negation nearby" test cannot work, because whether a `not`
#: denies the signal or *is* the signal depends on the trigger it attaches to:
#:
#:     "we were not in default"      -> denial   (no default)
#:     "we were not in compliance"   -> the breach itself
#:
#: Both contain "were not". The catalog's own pattern for a breach is
#: `not in compliance`, so the `not` is *inside* the trigger there and outside
#: it here -- which the adjacency window distinguishes and a sentence-wide
#: search cannot.
_ADJACENT_NEGATION = r"(?:\bno|\bnot|\bnever|\bwithout(?:\s+(?:a|any))?)\s+$"

#: Affirmative statements of compliance, which deny a breach without using a
#: negative next to the trigger. The lookbehind on the last entry keeps "we
#: were **not** in compliance with all covenants" out.
_COMPLIANCE_DENIAL_CUES = (
    r"\bwe (?:were|are|have been|had been|have remained|remain(?:ed|s)?) (?:currently )?in compliance\b",
    r"\bthe company (?:was|is|has been|remain(?:ed|s)?) (?:currently )?in compliance\b",
    r"(?<!not )\bin compliance with all\b",
    r"\bno (?:event of )?defaults? (?:has|have) occurred\b",
    r"\bnone of\b",
)

#: Cues that **override** a hypothetical reading because they assert a past or
#: present fact about the filer. Filing prose routinely mixes the two moods in
#: one sentence -- "we were not in compliance and our lenders could accelerate"
#: -- and without these the trailing modal would win.
_FACTUAL_OVERRIDES = (
    r"\bthere exists\b",
    r"\bexists? substantial doubt\b",
    r"\bsubstantial doubt exists\b",
    r"\braise[sd]? substantial doubt\b",
    r"\bcreate[sd]? substantial doubt\b",
    r"\bwe (?:have|had|were|was|are|is)\b",
    r"\bthe company (?:has|had|were|was|is)\b",
    r"\bwe (?:breached|defaulted|failed|obtained|received|entered|filed|suspended|eliminated)\b",
    r"\bas of (?:december|january|february|march|april|may|june|july|august|september|october|november)\b",
    r"\bduring (?:the year|fiscal|20\d\d)\b",
    r"\beffective\b",
)

_COMPILED_CONDITIONAL = tuple(re.compile(p) for p in _CONDITIONAL_CUES)
_COMPILED_MODAL = tuple(re.compile(p) for p in _MODAL_CUES)
_COMPILED_CROSS_REFERENCE = tuple(re.compile(p) for p in _CROSS_REFERENCE_CUES)
_COMPILED_ADJACENT_NEGATION = re.compile(_ADJACENT_NEGATION)
_COMPILED_COMPLIANCE_DENIAL = tuple(re.compile(p) for p in _COMPLIANCE_DENIAL_CUES)
_COMPILED_FACTUAL = tuple(re.compile(p) for p in _FACTUAL_OVERRIDES)

#: How far before the trigger an attached denial can sit. Long enough for
#: "without any " and no longer -- the whole point is adjacency.
ADJACENT_NEGATION_CHARS = 14

#: How far back from the trigger a cue can govern it. A cue at the start of a
#: 900-character sentence does not govern a clause at the end, and filing
#: sentences get that long. 220 characters is roughly two clauses.
CUE_WINDOW_CHARS = 220


def _matches(patterns: tuple[re.Pattern[str], ...], window: str) -> bool:
    return any(pattern.search(window) is not None for pattern in patterns)


def classify(sentence: str, trigger_start: int, trigger_end: int) -> Assertion:
    """Which mood the trigger at `[trigger_start, trigger_end)` sits in.

    `sentence` must already be lower-cased and punctuation-normalised (see
    `normalize.match_view`), because the cue patterns are written that way and
    the offsets must still line up with the original text.

    Precedence is deliberate and is the design, not an implementation detail:

    1. **Negation first.** An explicit denial beats everything; "no event of
       default has occurred" must never be read as a default.
    2. **Cross reference next.** A pointer asserts nothing, so it should not be
       promoted to a fact by a factual override elsewhere in the sentence.
    3. **Conditional before the factual override.** A conditional subordinates
       everything after it, including phrases that read as statements of fact
       on their own -- "If we *are unable* to refinance..." contains "we are".
    4. **Factual override before the modals**, so a sentence that states a fact
       and then speculates is read as the fact it states.
    5. **Modal last**, over the *entire* sentence, which is where the great
       bulk of Item 1A lands.
    """
    window = sentence[max(0, trigger_start - CUE_WINDOW_CHARS) : trigger_start]
    adjacent = sentence[max(0, trigger_start - ADJACENT_NEGATION_CHARS) : trigger_start]
    # The compliance cues have to reach *through* the trigger, because the
    # phrase they recognise overlaps it: the trigger for an affirmative
    # statement starts at "in compliance", so "we were in compliance" is only
    # visible in a window that includes the trigger itself. The cues stay safe
    # over that wider span because each is anchored so it cannot match the
    # negative wording -- "we were **not** in compliance" satisfies neither
    # `we were in compliance` nor `(?<!not )in compliance with all`.
    through_trigger = sentence[max(0, trigger_start - CUE_WINDOW_CHARS) : trigger_end]

    if _COMPILED_ADJACENT_NEGATION.search(adjacent) is not None:
        return Assertion.NEGATED
    if _matches(_COMPILED_COMPLIANCE_DENIAL, through_trigger):
        return Assertion.NEGATED
    if _matches(_COMPILED_CROSS_REFERENCE, sentence):
        return Assertion.CROSS_REFERENCE
    if _matches(_COMPILED_CONDITIONAL, window):
        return Assertion.HYPOTHETICAL
    if _matches(_COMPILED_FACTUAL, window):
        return Assertion.ASSERTED
    if _matches(_COMPILED_MODAL, sentence):
        return Assertion.HYPOTHETICAL
    return Assertion.ASSERTED
