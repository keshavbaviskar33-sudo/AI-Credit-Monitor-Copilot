"""The recall sweep exists to give recall an honest denominator.

Its correctness conditions are unusual: it is supposed to be *worse* than the
production catalog — broader, dumber, and full of boilerplate. What it must get
right is the bookkeeping, because the recall arithmetic is computed from
`caught_by_catalog` rather than from the labeller's judgement of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from credit_risk_copilot.nlp.models import RiskSignalCode
from credit_risk_copilot.nlp.recall_sweep import SWEEP_TERMS, sweep_candidates

ASSERTED = (
    "As of December 31, 2015 we were not in compliance with the leverage ratio covenant "
    "under our 2013 Credit Facility."
)
BOILERPLATE = (
    "If we fail to comply with the covenants in our credit agreement, our lenders could "
    "accelerate the indebtedness outstanding thereunder."
)

_HTML = """<html><body>
<p>Item 1A. Risk Factors</p>
<p>{boilerplate}</p>
<p>{filler}</p>
<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>
<p>{asserted}</p>
<p>{filler}</p>
<p>Item 8. Financial Statements and Supplementary Data</p>
<p>{filler}</p>
<p>Item 9. Changes in and Disagreements with Accountants</p>
<p>{filler}</p>
</body></html>"""


@pytest.fixture
def corpus(tmp_path: Path) -> list[dict[str, object]]:
    filler = "The Company continued to operate its reportable segments during the period. " * 6
    path = tmp_path / "filing.htm"
    path.write_text(
        _HTML.format(asserted=ASSERTED, boilerplate=BOILERPLATE, filler=filler),
        encoding="utf-8",
    )
    return [
        {
            "html_path": str(path),
            "cik": 1234,
            "accession": "0001234567-16-000001",
            "form": "10-K",
            "filed": "2016-03-30",
            "company": "Test Filer Inc.",
        }
    ]


class TestTheSweepIsBroaderThanTheCatalog:
    def test_it_surfaces_boilerplate_the_catalog_withholds(self) -> None:
        """The whole point. If the sweep only found what the catalog found,
        the denominator would be the numerator and recall would be 1.0 by
        construction."""
        assert "covenant" in SWEEP_TERMS[RiskSignalCode.COVENANT_BREACH]

    def test_every_catalog_code_has_a_sweep_term(self) -> None:
        """A code with no sweep term could never appear in the denominator, so
        its recall would silently be unmeasurable rather than zero."""
        assert set(SWEEP_TERMS) == set(RiskSignalCode)


class TestBookkeeping:
    def test_the_asserted_sentence_is_marked_caught(self, corpus: list[dict[str, object]]) -> None:
        rows = sweep_candidates(corpus, limit=200, seed=1)
        breach = [
            r
            for r in rows
            if r["code"] == RiskSignalCode.COVENANT_BREACH.value
            and "not in compliance" in str(r["quote"])
        ]

        assert breach
        assert all(r["caught_by_catalog"] for r in breach)

    def test_the_boilerplate_sentence_is_marked_not_caught(
        self, corpus: list[dict[str, object]]
    ) -> None:
        """It is surfaced (the sweep is broad) but not claimed (the catalog
        gated it). A labeller marking it `boilerplate` drops it from the
        denominator; marking it `true_signal` counts it as a miss."""
        rows = sweep_candidates(corpus, limit=200, seed=1)
        boilerplate = [
            r
            for r in rows
            if r["code"] == RiskSignalCode.COVENANT_BREACH.value
            and "fail to comply" in str(r["quote"])
        ]

        assert boilerplate
        assert not any(r["caught_by_catalog"] for r in boilerplate)

    def test_every_row_carries_an_empty_verdict_for_the_labeller(
        self, corpus: list[dict[str, object]]
    ) -> None:
        rows = sweep_candidates(corpus, limit=200, seed=1)

        assert rows
        assert all(r["verdict"] == "" for r in rows)
        assert all(r["accession"] == "0001234567-16-000001" for r in rows)


class TestRobustness:
    def test_the_limit_is_respected(self, corpus: list[dict[str, object]]) -> None:
        assert len(sweep_candidates(corpus, limit=1, seed=1)) == 1

    def test_a_missing_file_is_skipped_not_raised(self) -> None:
        """One unreadable filing must not abandon the whole sweep."""
        rows = sweep_candidates(
            [
                {
                    "html_path": "does/not/exist.htm",
                    "cik": 1,
                    "accession": "x",
                    "form": "10-K",
                    "filed": "2016-03-30",
                    "company": "Gone",
                }
            ],
            limit=10,
            seed=1,
        )

        assert rows == []

    def test_an_empty_corpus_yields_nothing(self) -> None:
        assert sweep_candidates([], limit=10, seed=1) == []
