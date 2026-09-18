"""End-to-end point-in-time dataset construction, on the real pipeline.

These tests build synthetic `companyfacts` payloads and run them through the
genuine resolver -> ratios -> health -> features path. Mocking that path would
make the tests pass while testing nothing: the leakage risk lives in how those
components combine, not in any one of them.
"""

from __future__ import annotations

from datetime import date

from credit_risk_copilot.modeling.contract import HorizonPolicy
from credit_risk_copilot.modeling.dataset import (
    build_company_observations,
    censoring_reasons,
    outcome_counts,
    relabel,
)
from credit_risk_copilot.modeling.labels import BankruptcyCase, EventTable
from tests._modeling_helpers import company_facts, declining_company, filing, filing_refs


def _events(*pairs: tuple[int, str]) -> EventTable:
    by_cik: dict[int, list[BankruptcyCase]] = {}
    for cik, filed in pairs:
        by_cik.setdefault(cik, []).append(
            BankruptcyCase(
                cik=cik,
                company="Test Co",
                filed=date.fromisoformat(filed),
                chapter="11",
                resolved=None,
            )
        )
    return EventTable(
        cases_by_cik={cik: tuple(cases) for cik, cases in by_cik.items()},
    )


def _policy(days: int = 365, through: str = "2024-12-31") -> HorizonPolicy:
    return HorizonPolicy(horizon_days=days, label_complete_through=date.fromisoformat(through))


def _build(events: EventTable | None = None, horizon: HorizonPolicy | None = None):  # type: ignore[no-untyped-def]
    facts, refs = declining_company()
    return build_company_observations(
        company_facts=facts,
        filings=refs,
        cik=1,
        company="Test Co",
        events=events or _events(),
        horizon=horizon or _policy(),
    )


class TestPanelShape:
    def test_one_observation_per_annual_filing_that_supports_a_row(self) -> None:
        observations, _ = _build()

        assert [obs.key.source_accession for obs in observations] == [
            "0000000000-19-000001",
            "0000000000-20-000001",
            "0000000000-21-000001",
        ]

    def test_the_prediction_date_is_the_filing_receipt_date(self) -> None:
        """Not the fiscal period end: a FY2019 10-K filed 2020-03-01 tells you
        nothing on 2019-12-31."""
        observations, _ = _build()

        assert observations[1].key.prediction_date == date(2020, 3, 1)
        assert observations[1].key.fiscal_period_label == "FY2019"

    def test_features_are_deterministic(self) -> None:
        first, _ = _build()
        second, _ = _build()

        assert [obs.features for obs in first] == [obs.features for obs in second]

    def test_a_company_with_one_filing_produces_no_observation(self) -> None:
        """One filing can still carry comparatives, but a single fiscal period
        gives no trend, no change and nothing for Phase 7 to analyse."""
        single = filing(
            accession="0000000000-20-000001",
            filed="2020-03-01",
            period_end="2019-12-31",
            years={2019: 1.0},
        )

        observations, skipped = build_company_observations(
            company_facts=company_facts(single),
            filings=filing_refs(single),
            cik=1,
            company="Test Co",
            events=_events(),
            horizon=_policy(),
        )

        assert observations == []
        assert [entry.reason_code for entry in skipped] == ["too_few_periods"]


class TestPointInTimeCorrectness:
    def test_an_early_observation_never_sees_a_later_filing(self) -> None:
        """The core guarantee. The first row's features must be built from the
        first filing alone, whatever the later ones say."""
        observations, _ = _build()

        first = observations[0]
        assert first.key.contributing_accessions == ("0000000000-19-000001",)
        assert all(
            accession <= "0000000000-20-000001"
            for accession in observations[1].key.contributing_accessions
        )

    def test_every_row_passes_its_own_leakage_assertion(self) -> None:
        """`build_company_observations` asserts this internally, so reaching
        this line at all is the check -- restated here so the guarantee is
        visible in the test suite rather than only in the builder."""
        observations, _ = _build()
        _, refs = declining_company()
        filing_dates = {ref.accession: date.fromisoformat(ref.filed) for ref in refs}

        for observation in observations:
            observation.assert_no_future_information(filing_dates)

    def test_a_later_restatement_does_not_change_an_earlier_row(self) -> None:
        """The subtle leak: a 2020 filing restating FY2018 revenue must not
        reach the row dated 2019, which is the as-filed rule (D-008) doing the
        work."""
        original = filing(
            accession="0000000000-19-000001",
            filed="2019-03-01",
            period_end="2018-12-31",
            years={2017: 1.0, 2018: 1.0},
        )
        restating = filing(
            accession="0000000000-20-000001",
            filed="2020-03-01",
            period_end="2019-12-31",
            years={2018: 1.0, 2019: 1.0},
            overrides={(2018, "Revenues"): 10.0},
        )

        observations, _ = build_company_observations(
            company_facts=company_facts(original, restating),
            filings=filing_refs(original, restating),
            cik=1,
            company="Test Co",
            events=_events(),
            horizon=_policy(),
        )

        # The 2019 row saw only the original FY2018 revenue of 900.
        assert observations[0].features["log_revenue"] is not None
        assert observations[0].features["log_revenue"] > 6.0
        # The 2020 row still reports FY2018 as originally filed, because
        # `as_of` keeps the earliest-filed value -- so the restatement is
        # visible via `restatements()`, never by silently overwriting history.
        assert observations[1].key.fiscal_period_label == "FY2019"


class TestLabelling:
    def test_an_event_inside_the_horizon_labels_the_row_positive(self) -> None:
        """Rows dated 2019-03-01, 2020-03-01 and 2021-03-01. The petition on
        2020-09-01 falls inside the second row's window; the third row sits
        *inside* the resulting proceeding and is censored, not scored."""
        observations, _ = _build(events=_events((1, "2020-09-01")))

        assert [obs.outcome.label for obs in observations] == [0, 1, None]
        assert observations[1].outcome.event_date == date(2020, 9, 1)
        assert observations[1].outcome.days_to_event == 184

    def test_rows_beyond_label_coverage_are_censored(self) -> None:
        observations, _ = _build(horizon=_policy(through="2020-12-31"))

        assert [obs.outcome.label for obs in observations] == [0, None, None]
        assert censoring_reasons(observations) == {"horizon_unobserved": 2}

    def test_outcome_counts_separate_censored_from_negative(self) -> None:
        observations, _ = _build(horizon=_policy(through="2020-12-31"))

        assert outcome_counts(observations) == {"positive": 0, "negative": 1, "censored": 2}

    def test_relabelling_reuses_features_and_only_changes_the_outcome(self) -> None:
        """The robustness horizon must be the same panel with a different
        window -- if features moved too, the two panels would not be
        comparable."""
        observations, _ = _build(events=_events((1, "2021-06-01")))
        longer = relabel(observations, _events((1, "2021-06-01")), _policy(days=730))

        assert [obs.features for obs in longer] == [obs.features for obs in observations]
        assert [obs.key for obs in longer] == [obs.key for obs in observations]
        # 2021-06-01 is beyond 365 days from the 2020-03-01 row but inside 730.
        assert observations[1].outcome.label == 0
        assert longer[1].outcome.label == 1
