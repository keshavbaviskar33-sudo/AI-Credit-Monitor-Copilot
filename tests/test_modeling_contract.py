"""The point-in-time contract, and the assertions that enforce it.

These are the tests that matter most in Phase 8. Every other measurement in
the phase is worthless if a feature can see the future, and "the builder was
written carefully" is not a guarantee -- so each rule is tested by deliberately
violating it and checking that the violation is refused.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from credit_risk_copilot.modeling.contract import (
    HorizonPolicy,
    LeakageError,
    Observation,
    ObservationKey,
    Outcome,
)


def _key(**overrides: object) -> ObservationKey:
    defaults: dict[str, object] = {
        "cik": 1,
        "company": "Test Co",
        "prediction_date": date(2019, 3, 1),
        "information_cutoff": date(2019, 3, 1),
        "source_accession": "0000000000-19-000001",
        "source_form": "10-K",
        "fiscal_period_label": "FY2018",
        "contributing_accessions": ("0000000000-19-000001",),
    }
    defaults.update(overrides)
    return ObservationKey(**defaults)  # type: ignore[arg-type]


class TestObservationKey:
    def test_cutoff_after_prediction_date_is_refused(self) -> None:
        """Pydantic wraps a validator's `LeakageError` in `ValidationError`,
        so construction-time violations surface as that; the leakage message
        is preserved inside it, and the explicit
        `assert_no_future_information` check below still raises
        `LeakageError` directly."""
        with pytest.raises(ValidationError, match="is after prediction_date"):
            _key(information_cutoff=date(2019, 6, 1))

    def test_cutoff_equal_to_prediction_date_is_the_normal_case(self) -> None:
        key = _key()
        assert key.information_cutoff == key.prediction_date


class TestLeakageAssertion:
    def _observation(self, accessions: tuple[str, ...]) -> Observation:
        return Observation(
            key=_key(contributing_accessions=accessions),
            features={"log_total_assets": 1.0},
            outcome=Outcome(label=0, horizon_end=date(2020, 3, 1)),
        )

    def test_a_contributing_filing_from_the_future_is_caught(self) -> None:
        """The exact failure the whole phase is designed to prevent: a 2021
        filing restating FY2018 reaching a row dated 2019."""
        observation = self._observation(("0000000000-19-000001", "0000000000-21-000009"))
        filing_dates = {
            "0000000000-19-000001": date(2019, 3, 1),
            "0000000000-21-000009": date(2021, 2, 20),
        }

        with pytest.raises(LeakageError, match="after the information cutoff"):
            observation.assert_no_future_information(filing_dates)

    def test_a_filing_on_the_cutoff_date_itself_is_allowed(self) -> None:
        """The triggering filing is filed *on* the cutoff -- it is the new
        information the observation exists to react to."""
        observation = self._observation(("0000000000-19-000001",))

        observation.assert_no_future_information({"0000000000-19-000001": date(2019, 3, 1)})

    def test_an_accession_with_no_known_filing_date_is_refused(self) -> None:
        """Unverifiable is not the same as fine: a contributing accession whose
        date we cannot check must stop the build, not pass silently."""
        observation = self._observation(("0000000000-19-000001", "unknown-accession"))

        with pytest.raises(LeakageError, match="no known filing date"):
            observation.assert_no_future_information({"0000000000-19-000001": date(2019, 3, 1)})


class TestOutcome:
    def test_a_positive_must_carry_its_event_date(self) -> None:
        with pytest.raises(ValueError, match="must carry its event_date"):
            Outcome(label=1, horizon_end=date(2020, 3, 1))

    def test_a_negative_must_not_carry_an_event_date(self) -> None:
        with pytest.raises(ValueError, match="must not carry an event_date"):
            Outcome(label=0, horizon_end=date(2020, 3, 1), event_date=date(2019, 8, 1))

    def test_a_censored_row_must_state_why(self) -> None:
        with pytest.raises(ValueError, match="must state why"):
            Outcome(label=None, horizon_end=date(2020, 3, 1))

    def test_only_labelled_outcomes_are_usable(self) -> None:
        assert Outcome(label=0, horizon_end=date(2020, 3, 1)).is_usable
        assert Outcome(label=1, horizon_end=date(2020, 3, 1), event_date=date(2019, 9, 1)).is_usable
        assert not Outcome(
            label=None, horizon_end=date(2020, 3, 1), censoring_reason="beyond coverage"
        ).is_usable


class TestHorizonPolicy:
    def _policy(self, days: int = 365) -> HorizonPolicy:
        return HorizonPolicy(horizon_days=days, label_complete_through=date(2020, 12, 31))

    def test_horizon_end_is_the_prediction_date_plus_the_window(self) -> None:
        assert self._policy().horizon_end(date(2019, 3, 1)) == date(2020, 2, 29)

    def test_a_window_ending_inside_coverage_is_observable(self) -> None:
        assert self._policy().is_observable(date(2019, 12, 31))

    def test_a_window_ending_past_coverage_is_not(self) -> None:
        """The boundary case that decides whether the most recent -- and most
        interesting -- rows are scored as survivals or censored."""
        assert not self._policy().is_observable(date(2020, 6, 1))

    def test_a_longer_horizon_shortens_the_usable_span(self) -> None:
        assert self._policy(365).describe()["latest_usable_prediction_date"] == "2020-01-01"
        assert self._policy(730).describe()["latest_usable_prediction_date"] == "2019-01-01"
