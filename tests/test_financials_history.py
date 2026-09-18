"""Multi-filing history assembly (`financials/history.py`).

The Phase 1-7 audit found that this path -- the one D-001 (monitoring) and
D-008 (as-filed) both depend on -- existed only as unit-tested code with no
real caller. These tests cover the assembly itself; `scripts/evaluate_multi_filing.py`
(QM-04) exercises it on the real corpus.

The emphasis is on the *diagnostics*: a silently dropped filing is a silently
missing year of history, and Phase 8 builds features out of those years.
"""

from __future__ import annotations

from credit_risk_copilot.financials.history import (
    accessions_with_facts,
    resolve_company_history,
)
from tests._modeling_helpers import FakeFilingRef, company_facts, declining_company, filing


class TestAccessionsWithFacts:
    def test_lists_every_accession_the_payload_carries(self) -> None:
        facts, _ = declining_company()

        assert accessions_with_facts(facts) == {
            "0000000000-19-000001",
            "0000000000-20-000001",
            "0000000000-21-000001",
        }

    def test_an_empty_payload_has_none(self) -> None:
        assert accessions_with_facts({"facts": {}}) == frozenset()


class TestResolveCompanyHistory:
    def test_every_filing_with_facts_resolves(self) -> None:
        facts, refs = declining_company()

        history = resolve_company_history(facts, refs, cik=1, company="Test Co")

        assert history.resolved_count == 3
        assert history.skipped_count == 0
        assert [f.accession for f in history.financials.filings] == [
            "0000000000-19-000001",
            "0000000000-20-000001",
            "0000000000-21-000001",
        ]

    def test_filings_are_ordered_by_receipt_date(self) -> None:
        facts, refs = declining_company()

        history = resolve_company_history(facts, list(reversed(refs)), cik=1, company="Test Co")

        filed = [f.filed for f in history.financials.filings]
        assert filed == sorted(filed)

    def test_a_pre_xbrl_filing_is_skipped_with_a_stated_reason(self) -> None:
        """Most real skips are this: `submissions` lists 10-Ks going back
        decades, and the ones before the filer's XBRL phase-in carry no facts
        at all. That is a data-coverage fact, not a code failure, and the
        distinction has to survive into the diagnostics."""
        facts, refs = declining_company()
        refs.append(
            FakeFilingRef(
                cik=1,
                accession="0000000000-09-000001",
                form="10-K",
                filed="2009-03-01",
                period="2008-12-31",
            )
        )

        history = resolve_company_history(facts, refs, cik=1, company="Test Co")

        assert history.resolved_count == 3
        assert history.skip_reasons() == {"no_xbrl_facts": 1}
        assert "XBRL phase-in" in history.skipped[0].message

    def test_a_filing_without_a_report_date_is_skipped_separately(self) -> None:
        """A different cause from `no_xbrl_facts`, and worth telling apart:
        without a fiscal anchor there is no way to decide which of the
        filing's facts are its annual periods."""
        contribution = filing(
            accession="0000000000-20-000001",
            filed="2020-03-01",
            period_end="2019-12-31",
            years={2018: 1.0, 2019: 1.0},
        )
        refs = [
            FakeFilingRef(
                cik=1,
                accession="0000000000-20-000001",
                form="10-K",
                filed="2020-03-01",
                period="",
            )
        ]

        history = resolve_company_history(company_facts(contribution), refs, cik=1, company="T")

        assert history.resolved_count == 0
        assert history.skip_reasons() == {"no_period_end": 1}

    def test_a_duplicate_accession_is_resolved_once(self) -> None:
        facts, refs = declining_company()

        history = resolve_company_history(facts, [*refs, refs[0]], cik=1, company="Test Co")

        assert history.resolved_count == 3


class TestPointInTimeGate:
    def test_filings_after_the_cutoff_are_never_resolved(self) -> None:
        """The gate is applied before resolution, not after: a filing excluded
        here can never contribute a fact, a period or a provenance entry to
        anything downstream."""
        facts, refs = declining_company()

        history = resolve_company_history(
            facts, refs, cik=1, company="Test Co", filed_on_or_before="2020-03-01"
        )

        assert history.resolved_count == 2
        assert all(f.filed <= "2020-03-01" for f in history.financials.filings)
        # The excluded filing is not reported as a skip either -- it was never
        # a candidate, which is different from having failed.
        assert history.skipped_count == 0

    def test_a_filing_on_the_cutoff_date_is_included(self) -> None:
        facts, refs = declining_company()

        history = resolve_company_history(
            facts, refs, cik=1, company="Test Co", filed_on_or_before="2019-03-01"
        )

        assert history.resolved_count == 1

    def test_the_cutoff_limits_which_periods_are_visible(self) -> None:
        facts, refs = declining_company()

        early = resolve_company_history(
            facts, refs, cik=1, company="Test Co", filed_on_or_before="2019-03-01"
        )
        late = resolve_company_history(facts, refs, cik=1, company="Test Co")

        early_periods = {p for f in early.financials.filings for p in f.period_labels}
        late_periods = {p for f in late.financials.filings for p in f.period_labels}
        assert "FY2020" not in early_periods
        assert "FY2020" in late_periods
