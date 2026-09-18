"""The assertion gate, tested on the sentences that motivated it.

Every `ASSERTED` example here is real filing language from the Phase 4 golden
set (Peabody, Frontier, SandRidge FY2015-2019); every `HYPOTHETICAL` example is
risk-factor prose from the same corpus or from the healthy cohort. That matters
because the failure mode being guarded against is precisely a rule that looks
sensible in invented examples and fires on every real 10-K.
"""

from __future__ import annotations

from credit_risk_copilot.nlp.assertion import classify
from credit_risk_copilot.nlp.models import Assertion
from credit_risk_copilot.nlp.normalize import match_view


def _classify(sentence: str, trigger: str) -> Assertion:
    """Classify `trigger` where it appears in `sentence`."""
    view = match_view(sentence)
    start = view.index(match_view(trigger))
    return classify(view, start, start + len(trigger))


class TestAsserted:
    def test_the_statutory_going_concern_conclusion(self) -> None:
        sentence = (
            "Based on the continued uncertainty around global coal fundamentals, among other "
            "matters, there exists substantial doubt whether we will be able to continue as a "
            "going concern."
        )
        assert _classify(sentence, "going concern") is Assertion.ASSERTED

    def test_a_dependency_statement_is_an_assertion(self) -> None:
        sentence = (
            "Our ability to continue as a going concern is dependent upon our ability to "
            "consummate the Restructuring and to generate sufficient liquidity."
        )
        assert _classify(sentence, "going concern") is Assertion.ASSERTED

    def test_a_fact_followed_by_speculation_reads_as_the_fact(self) -> None:
        """The precedence rule doing its job: `we were` precedes the trigger,
        so the trailing modal does not win."""
        sentence = (
            "We were not in compliance with the fixed charge coverage covenant at year end, "
            "and our lenders could accelerate the obligations."
        )
        assert _classify(sentence, "not in compliance") is Assertion.ASSERTED

    def test_a_dated_event_is_an_assertion(self) -> None:
        sentence = (
            "During the year ended December 31, 2015 we obtained waivers of the financial "
            "covenants under the 2013 Credit Facility."
        )
        assert _classify(sentence, "waivers") is Assertion.ASSERTED


class TestHypothetical:
    def test_a_conditional_risk_factor(self) -> None:
        sentence = (
            "If we are unable to refinance our indebtedness, we may be unable to continue as a "
            "going concern."
        )
        assert _classify(sentence, "going concern") is Assertion.HYPOTHETICAL

    def test_a_trigger_in_subject_position_governed_by_a_later_modal(self) -> None:
        """The Walmart defect. A backward-only cue search finds nothing before
        "downgrade" but the word "any", so the sentence was read as an asserted
        downgrade of a company with a AA credit rating."""
        sentence = (
            "Any downgrade of our credit ratings by a credit rating agency could increase our "
            "future borrowing costs or impair our ability to access capital markets."
        )
        assert _classify(sentence, "downgrade of our credit ratings") is Assertion.HYPOTHETICAL

    def test_a_failure_to_comply_construction(self) -> None:
        sentence = (
            "Any failure to comply with the covenants in our credit agreement would permit the "
            "lenders to declare an event of default."
        )
        assert _classify(sentence, "event of default") is Assertion.HYPOTHETICAL

    def test_a_no_assurance_construction(self) -> None:
        sentence = (
            "There can be no assurance that we will obtain waivers of the financial covenants "
            "on acceptable terms."
        )
        assert _classify(sentence, "waivers") is Assertion.HYPOTHETICAL


class TestNegated:
    def test_an_explicit_denial_of_default(self) -> None:
        sentence = "No event of default has occurred and is continuing under the Credit Facility."
        assert _classify(sentence, "event of default") is Assertion.NEGATED

    def test_a_statement_of_compliance(self) -> None:
        sentence = (
            "As of December 31, 2019 we were in compliance with all covenants under our credit "
            "agreement and our outstanding notes."
        )
        assert _classify(sentence, "covenants") is Assertion.NEGATED

    def test_negation_beats_a_factual_override(self) -> None:
        """`we were` would otherwise assert. A denial has to outrank it, or
        every statement of compliance becomes a breach."""
        sentence = "We were not in default under any of our debt agreements during the period."
        assert _classify(sentence, "in default") is Assertion.NEGATED


class TestCrossReference:
    def test_a_pointer_to_a_note_asserts_nothing(self) -> None:
        sentence = (
            "Refer to Note 1 of the Notes to Consolidated Financial Statements for further "
            "discussion of the Company's ability to continue as a going concern."
        )
        assert _classify(sentence, "going concern") is Assertion.CROSS_REFERENCE

    def test_a_cross_reference_outranks_a_factual_override(self) -> None:
        """ "the Company has" would assert; a pointer still asserts nothing."""
        sentence = (
            "See Item 7 for a discussion of the covenant breach the Company has disclosed "
            "elsewhere in this Annual Report."
        )
        assert _classify(sentence, "covenant breach") is Assertion.CROSS_REFERENCE


class TestDefault:
    def test_a_plain_statement_with_no_cues_is_asserted(self) -> None:
        """The fallback. A sentence carrying neither a modal nor a denial nor a
        pointer is the filer stating something."""
        sentence = "The Company filed a voluntary petition under chapter 11 on April 13, 2016."
        assert _classify(sentence, "chapter 11") is Assertion.ASSERTED
