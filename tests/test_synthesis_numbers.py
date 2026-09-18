"""Number grounding: the half of FR-17 that decides what "present" means."""

from __future__ import annotations

import pytest

from credit_risk_copilot.synthesis.numbers import mentions, ungrounded


def grounded(text: str, *values: float, evidence_text: str = "") -> bool:
    return ungrounded(text, frozenset(values), evidence_text) == ()


def test_a_rounded_restatement_is_grounded():
    """The case a naive equality check gets wrong on every correct draft."""
    assert grounded("ranks at the 97.8th percentile", 97.8312)
    assert grounded("ranks at the 98th percentile", 97.8312)


def test_rounding_to_a_different_number_is_not_grounded():
    """The precision the writer chose is the precision they are held to."""
    assert not grounded("ranks at the 97.9th percentile", 97.8312)
    assert not grounded("ranks at the 99th percentile", 97.8312)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("a lift of 2.04", 2.04),
        ("current ratio of 1.42", 1.4209),
        ("fell 0.31", -0.31),
        ("fell by -0.31", -0.31),
        ("changed by +0.084", 0.084),
        ("1,250 filings", 1250.0),
    ],
)
def test_common_financial_literals(claim, value):
    assert grounded(claim, value)


def test_a_percentage_is_tried_both_ways():
    """22% is 22.0 in a percentile field and 0.22 as a rate, and this layer
    cannot know which the evidence used."""
    assert grounded("appears in 22% of filings", 22.0)
    assert grounded("appears in 22% of filings", 0.22)
    assert not grounded("appears in 22% of filings", 0.31)


def test_scale_words_are_read():
    assert grounded("an impairment charge of $199.5 million", 199_500_000.0)
    assert grounded("an impairment charge of $199.5 million", 199.5)
    # The admissible gap scales with the unit: 199.5 million is stated to the
    # hundred-thousand, so 199,540,000 is the same number and 199,700,000 is not.
    assert grounded("an impairment charge of $199.5 million", 199_540_000.0)
    assert not grounded("an impairment charge of $199.5 million", 199_700_000.0)


def test_an_integer_admits_half_a_unit_and_no_more():
    assert grounded("37 signals fired", 37.0)
    assert grounded("37 signals fired", 37.4)
    assert not grounded("37 signals fired", 37.6)


def test_evidence_ids_do_not_contribute_digits():
    """Without masking, a fabricated figure could be grounded on the
    coincidence of an evidence ID's hex tail."""
    assert mentions("cited EV-MS-77ca0e19") == ()


def test_periods_and_accessions_are_grounded_on_the_evidence_text():
    """Facts the evidence states in words, not in floats."""
    assert grounded("over FY2014", evidence_text="liquidity: deteriorating over FY2014")
    assert not grounded("over FY2011", evidence_text="liquidity: deteriorating over FY2014")


def test_a_count_quoted_from_the_summary_is_grounded():
    """ "3 of 4 ratios" is a fact the summary writes and no float records."""
    assert grounded(
        "3 of 4 ratios are conclusive",
        evidence_text="liquidity: deteriorating over FY2014 (3 of 4 ratios conclusive)",
    )


def test_a_fabricated_number_is_reported_with_its_surface_form():
    assert ungrounded("ranks at the 62.5th percentile", frozenset({97.8}), "") == ("62.5",)
