"""Catalog invariants, and the decoys that caused real false positives.

The decoy tests are the valuable ones. Both entries in `TestSubstringDecoys`
are sentences from the Phase 4 golden set that a missing word boundary turned
into a distress signal for a company in excellent health -- and neither is the
kind of example anyone invents while writing the pattern. They are pinned here
so the boundary cannot be dropped again.
"""

from __future__ import annotations

import pytest

from credit_risk_copilot.nlp.catalog import CATALOG, CATALOG_BY_CODE, definition_for
from credit_risk_copilot.nlp.extract import extract_from_text
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode, Specificity


def _codes(text: str, *, emit_hypothetical: bool = False) -> set[RiskSignalCode]:
    return {
        signal.code
        for signal in extract_from_text(text, emit_hypothetical=emit_hypothetical)
        if signal.assertion is not Assertion.NEGATED
    }


class TestCatalogIsWellFormed:
    def test_every_code_has_a_definition(self) -> None:
        """A code with no patterns can never fire, which would be a silent
        hole rather than a visible gap."""
        assert set(CATALOG_BY_CODE) == set(RiskSignalCode)

    def test_every_definition_has_at_least_one_pattern(self) -> None:
        for definition in CATALOG:
            assert definition.patterns, definition.code

    def test_pattern_ids_are_unique(self) -> None:
        """A false positive must trace to exactly one editable line."""
        ids = [p.pattern_id for d in CATALOG for p in d.patterns]
        assert len(ids) == len(set(ids))

    def test_every_pattern_is_lower_case(self) -> None:
        """Patterns run against `match_view`, which is lower-cased. An
        upper-case literal in a pattern would simply never match."""
        for definition in CATALOG:
            for pattern in definition.patterns:
                literals = "".join(c for c in pattern.regex if c.isalpha())
                assert literals == literals.lower(), pattern.pattern_id

    def test_every_definition_declares_a_specificity(self) -> None:
        for definition in CATALOG:
            assert isinstance(definition.specificity, Specificity)

    def test_definition_lookup_round_trips(self) -> None:
        for definition in CATALOG:
            assert definition_for(definition.code) is definition


class TestSubstringDecoys:
    def test_ongoing_concern_is_not_going_concern(self) -> None:
        """Coca-Cola's risk factors say "ongoing concern" four times -- about
        obesity, plastic waste and climate. Without a word boundary the
        healthiest filer in the corpus reports going-concern doubt."""
        text = (
            "There is ongoing concern among consumers, public health professionals and "
            "government agencies about the health problems associated with obesity."
        )
        assert RiskSignalCode.GOING_CONCERN_DOUBT not in _codes(text)

    def test_consecutive_quarterly_dividend_is_not_a_dividend_cut(self) -> None:
        """ "cut" inside "conse-cut-ive". Pfizer's 349th consecutive quarterly
        dividend was read as a dividend reduction."""
        text = (
            "The first-quarter 2026 cash dividend will be our 349th consecutive quarterly "
            "dividend paid to shareholders of record."
        )
        assert RiskSignalCode.DIVIDEND_SUSPENSION not in _codes(text)

    def test_indebtedness_is_not_bare_debt(self) -> None:
        """`\\bdebt\\b` rather than `debt`, so "indebtedness" does not satisfy
        a pattern that wants a debt instrument."""
        import re

        from credit_risk_copilot.nlp.catalog import _DEBT

        assert re.search(_DEBT, "our total indebtedness increased") is None
        assert re.search(_DEBT, "our total debt increased") is not None


class TestSignalsFireOnRealLanguage:
    """One asserted example per code, in the wording filings actually use."""

    @pytest.mark.parametrize(
        ("code", "text"),
        [
            (
                RiskSignalCode.GOING_CONCERN_DOUBT,
                "These factors, among others, create substantial doubt about the Company's "
                "ability to continue as a going concern.",
            ),
            (
                RiskSignalCode.COVENANT_BREACH,
                "As of December 31, 2015 we were not in compliance with the leverage ratio "
                "covenant under our 2013 Credit Facility.",
            ),
            (
                RiskSignalCode.COVENANT_WAIVER_OR_AMENDMENT,
                "During 2016 we obtained waivers of the financial covenants from the lenders "
                "under our senior secured credit facility.",
            ),
            (
                RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION,
                "An event of default has occurred under the indenture governing our senior "
                "notes as a result of the missed interest payment.",
            ),
            (
                RiskSignalCode.DEBT_RESTRUCTURING,
                "We entered into a restructuring support agreement with holders of a majority "
                "of our senior notes on March 4, 2020.",
            ),
            (
                RiskSignalCode.BANKRUPTCY_CONTEMPLATED,
                "The Company filed a voluntary petition for relief under chapter 11 of the "
                "Bankruptcy Code on April 13, 2016.",
            ),
            (
                RiskSignalCode.LIQUIDITY_SHORTFALL,
                "Our cash on hand and cash from operations will not be sufficient to fund our "
                "scheduled debt service obligations for the next twelve months.",
            ),
            (
                RiskSignalCode.MATERIAL_WEAKNESS,
                "Management identified a material weakness in internal control over financial "
                "reporting relating to the review of oil and gas reserve estimates.",
            ),
            (
                RiskSignalCode.DIVIDEND_SUSPENSION,
                "In February 2016 our board of directors suspended the quarterly dividend on "
                "our common stock indefinitely.",
            ),
            (
                RiskSignalCode.DELISTING_NOTICE,
                "On January 8, 2016 we received a notice from the NYSE that we were not in "
                "compliance with the continued listing standard relating to market "
                "capitalization.",
            ),
            (
                RiskSignalCode.CREDIT_RATING_DOWNGRADE,
                "Moody's downgraded our corporate family rating to Caa3 from Caa1 during the "
                "fourth quarter of the year.",
            ),
            (
                RiskSignalCode.ASSET_IMPAIRMENT,
                "We recorded a goodwill impairment charge of $1.4 billion during the year "
                "ended December 31, 2015.",
            ),
        ],
    )
    def test_the_code_fires_as_asserted(self, code: RiskSignalCode, text: str) -> None:
        assert code in _codes(text)


#: Risk-factor boilerplate that **does** match a catalog pattern, so the
#: assertion gate is the only thing standing between it and a false positive.
#: These are the cases that exercise the gate.
_GATED_BOILERPLATE = [
    "Any downgrade of our credit ratings could increase our future borrowing costs and "
    "impair our access to capital markets.",
    "If our liquidity were to decline materially, we might be required to seek protection "
    "under chapter 11 of the Bankruptcy Code.",
    "If we breach a covenant under our credit agreement, the lenders could declare all "
    "amounts outstanding immediately due and payable.",
    "There can be no assurance that we will be able to obtain waivers of the financial "
    "covenants on acceptable terms.",
]

#: Risk-factor boilerplate that matches **no** pattern at all, because the
#: patterns require the wording of a disclosure rather than of a warning
#: ("an event of default *has occurred*", not "could result in an event of
#: default"). A second, independent line of defence.
_UNMATCHED_BOILERPLATE = [
    "If we are unable to generate sufficient cash flow, we may be unable to continue as a "
    "going concern.",
    "A failure to comply with the covenants in our credit agreement could result in an "
    "event of default and the acceleration of our indebtedness.",
    "We may be required to record impairment charges in future periods if market "
    "conditions deteriorate.",
]


class TestHypotheticalBoilerplateIsGated:
    """The whole point of the phase, and it has two independent defences.

    Keeping them apart matters: a test that only asserted "no signal" would
    pass just as well if every pattern silently stopped matching, and would
    never notice that the gate had broken.
    """

    @pytest.mark.parametrize("text", _GATED_BOILERPLATE)
    def test_matching_boilerplate_is_withheld_by_the_gate(self, text: str) -> None:
        assert _codes(text) == set()

    @pytest.mark.parametrize("text", _GATED_BOILERPLATE)
    def test_it_really_did_reach_the_gate(self, text: str) -> None:
        """Proves the previous test is testing the gate rather than a pattern
        that happens not to match."""
        signals = extract_from_text(text, emit_hypothetical=True)

        assert signals
        assert all(s.assertion is Assertion.HYPOTHETICAL for s in signals)

    @pytest.mark.parametrize("text", _UNMATCHED_BOILERPLATE)
    def test_warning_wording_does_not_match_a_disclosure_pattern(self, text: str) -> None:
        assert extract_from_text(text, emit_hypothetical=True) == ()

    def test_gated_signals_are_withheld_not_discarded(self) -> None:
        """ "this filer's risk factors newly discuss covenant breach" is a
        weaker signal, not a non-signal, so the caller can ask for it."""
        text = _GATED_BOILERPLATE[2]

        assert _codes(text) == set()
        assert _codes(text, emit_hypothetical=True) == {RiskSignalCode.COVENANT_BREACH}


class TestImpairmentContextGate:
    def test_accounting_policy_prose_does_not_fire(self) -> None:
        """ "impairment" is constant in policy discussion; the definition
        requires a charge, an amount or a period."""
        text = (
            "Goodwill is tested for impairment at the reporting unit level using a "
            "qualitative assessment of relevant events and circumstances."
        )
        assert RiskSignalCode.ASSET_IMPAIRMENT not in _codes(text)

    def test_a_quantified_charge_does_fire(self) -> None:
        text = (
            "We recognized a full cost ceiling impairment of $4.5 billion during the year "
            "ended December 31, 2015."
        )
        assert RiskSignalCode.ASSET_IMPAIRMENT in _codes(text)


class TestDevelopmentSampleRegressions:
    """The eleven false positives found by hand-labelling 48 emitted signals.

    Every sentence here is real filing text from the Phase 10 corpus. They are
    the reason the catalog grew an `excludes_context` field and the assertion
    module grew two cues, and they are pinned because each one is a shape that
    looks obviously wrong only *after* someone has read it in context.
    """

    def test_nyse_listing_non_compliance_is_not_a_covenant_breach(self) -> None:
        """Ferrellgas and Titan Energy. "not in compliance" with a *listing
        standard* has nothing to do with a debt covenant."""
        text = (
            "On January 12, 2016, we were notified by the NYSE that we were not in compliance "
            "with NYSE's continued listing criteria because the average closing price of the "
            "common units had been less than $1.00 for 30 consecutive trading days."
        )
        codes = _codes(text)

        assert RiskSignalCode.COVENANT_BREACH not in codes
        assert RiskSignalCode.DELISTING_NOTICE in codes

    def test_a_facilitys_own_terms_are_not_a_default(self) -> None:
        """Clearwater Paper. The sentence describes when a covenant applies,
        in the indicative -- so the assertion gate passes it and only the
        contract-terms exclusion can catch it."""
        text = (
            "In addition, our senior secured revolving credit facility requires, among other "
            "things, that we maintain a minimum fixed charge coverage ratio of at least "
            "1.0-to-1.0 when availability falls below $50 million or an event of default exists."
        )
        assert RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION not in _codes(text)

    def test_customary_termination_events_are_not_a_covenant_breach(self) -> None:
        """Alpha Natural Resources."""
        text = (
            "The A/R Facility includes termination events customary for facilities of this type "
            "(with typical grace periods, where applicable), including, among other things, "
            "breaches of covenants and inaccuracy of representations."
        )
        assert RiskSignalCode.COVENANT_BREACH not in _codes(text)

    def test_a_negation_after_the_trigger_is_not_a_default(self) -> None:
        """Fairway Group. "events of default have **not** occurred" -- the
        adjacency rule looks before the trigger, so the pattern itself has to
        require an adjacent completed verb."""
        text = (
            "The restricted payment basket remains available as long as our corporate rating is "
            "B or higher with a stable outlook, and as long as certain events of default have "
            "not occurred."
        )
        assert RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION not in _codes(text)

    def test_quoting_the_accounting_standard_is_not_a_disclosure(self) -> None:
        """Molycorp quotes ASU 2014-15's definition of substantial doubt. It
        is a definition, and it is about "an entity", not about this filer."""
        text = (
            "Substantial doubt about an entity's ability to continue as a going concern exists "
            "when relevant conditions and events indicate that it is probable that the entity "
            "will be unable to meet its obligations as they become due within one year."
        )
        assert RiskSignalCode.LIQUIDITY_SHORTFALL not in _codes(text)

    def test_a_capital_programme_shortfall_is_not_a_liquidity_shortfall(self) -> None:
        """Breitburn. About capex against production decline, not about
        meeting obligations."""
        text = (
            "We also believe that our reduced capital program in 2016 will not be sufficient to "
            "offset production declines across our operated properties."
        )
        assert RiskSignalCode.LIQUIDITY_SHORTFALL not in _codes(text)

    def test_being_rated_below_investment_grade_is_not_a_downgrade(self) -> None:
        """Eastman Kodak. A standing condition, not the event this code names."""
        text = (
            "In carrying out its commercial business strategy, the current non-investment grade "
            "credit ratings have resulted in requirements that Kodak either prepay obligations "
            "or post significant amounts of collateral."
        )
        assert RiskSignalCode.CREDIT_RATING_DOWNGRADE not in _codes(text)

    def test_cannot_provide_assurance_is_hypothetical(self) -> None:
        """Amplify Energy. The hedge without the verb "be"."""
        text = (
            "We cannot provide assurance that any of our current ratings will remain in effect "
            "for any given period of time or that a rating will not be lowered or withdrawn "
            "entirely by a rating agency."
        )
        assert RiskSignalCode.CREDIT_RATING_DOWNGRADE not in _codes(text)

    def test_have_remained_in_compliance_is_a_denial(self) -> None:
        """Eagle Bulk Shipping. The compliance-denial cue listed "have been"
        but not "have remained", so an affirmative statement of compliance was
        emitted as an asserted breach."""
        text = (
            "We have remained in compliance with the amended collateral covenants during the "
            "accounting periods ended March 31, 2011 and June 30, 2011."
        )
        assert RiskSignalCode.COVENANT_BREACH not in _codes(text)

    def test_the_genuine_versions_still_fire(self) -> None:
        """The other half of every exclusion: it must not have silenced the
        real disclosure it sits next to."""
        real = [
            (
                RiskSignalCode.COVENANT_BREACH,
                "As of December 31, 2011, we were not in compliance with the covenants "
                "contained in our Senior Secured Credit Facilities.",
            ),
            (
                RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION,
                "As we have not repaid all outstanding obligations under the ABL Facility, an "
                "event of default has occurred and the lenders are entitled to exercise their "
                "remedies.",
            ),
            (
                RiskSignalCode.LIQUIDITY_SHORTFALL,
                "The Company believes that forecasted cash and available credit capacity will "
                "not be sufficient to meet commitments as they come due over the next twelve "
                "months.",
            ),
            (
                RiskSignalCode.CREDIT_RATING_DOWNGRADE,
                "On December 20, 2018, Moody's Investors Services downgraded our credit rating "
                "on our senior unsecured notes to Caa3 from Caa1.",
            ),
        ]
        for code, text in real:
            assert code in _codes(text), code
