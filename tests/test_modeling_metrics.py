"""Evaluation metrics: the alert-rate view, calibration, and grouped intervals.

The metrics a credit-monitoring product is judged on are not the defaults.
These tests pin the three choices that differ from a generic classifier
write-up: PR-AUC is quoted against the event rate rather than 0.5, alert-rate
precision/recall is computed on a review queue of fixed depth, and bootstrap
intervals resample *companies* rather than rows.
"""

from __future__ import annotations

import numpy as np
import pytest

from credit_risk_copilot.modeling.metrics import ALERT_RATES, delta_auc_ci, evaluate


def _perfect(n: int = 100, events: int = 10):  # type: ignore[no-untyped-def]
    y = [1] * events + [0] * (n - events)
    scores = [0.9] * events + [0.1] * (n - events)
    companies = list(range(n))
    return y, scores, companies


class TestHeadlineMetrics:
    def test_a_perfect_ranker_scores_one(self) -> None:
        y, scores, companies = _perfect()

        result = evaluate(y, scores, companies, bootstrap=False)

        assert result.roc_auc == pytest.approx(1.0)
        assert result.pr_auc == pytest.approx(1.0)

    def test_pr_auc_baseline_is_the_event_rate_not_half(self) -> None:
        """PR-AUC is meaningless without it: 0.30 is excellent at a 3% base
        rate and poor at a 50% one."""
        y, scores, companies = _perfect(n=100, events=3)

        result = evaluate(y, scores, companies, bootstrap=False)

        assert result.pr_auc_baseline == pytest.approx(0.03)
        assert result.event_rate == pytest.approx(0.03)

    def test_a_random_ranker_scores_about_half_on_roc(self) -> None:
        rng = np.random.default_rng(0)
        y = [1] * 50 + [0] * 450
        scores = rng.random(500).tolist()

        result = evaluate(y, scores, list(range(500)), bootstrap=False)

        assert 0.4 < (result.roc_auc or 0.0) < 0.6

    def test_accuracy_is_not_reported_anywhere(self) -> None:
        """A model predicting 'no bankruptcy' for everything is >95% accurate
        and worthless, so the field does not exist."""
        y, scores, companies = _perfect()

        result = evaluate(y, scores, companies, bootstrap=False)

        assert not hasattr(result, "accuracy")


class TestAlertRates:
    def test_every_configured_alert_rate_is_reported(self) -> None:
        y, scores, companies = _perfect()

        result = evaluate(y, scores, companies, bootstrap=False)

        assert tuple(a.alert_rate for a in result.alert_rates) == ALERT_RATES

    def test_recall_at_ten_percent_captures_a_perfectly_ranked_cohort(self) -> None:
        y, scores, companies = _perfect(n=100, events=10)

        result = evaluate(y, scores, companies, bootstrap=False)
        ten_percent = next(a for a in result.alert_rates if a.alert_rate == 0.10)

        assert ten_percent.flagged == 10
        assert ten_percent.events_captured == 10
        assert ten_percent.recall == pytest.approx(1.0)
        assert ten_percent.precision == pytest.approx(1.0)

    def test_rows_reviewed_per_event_is_the_queue_view_of_precision(self) -> None:
        """Precision 0.25 means an analyst reads four filings per real
        finding, which is the number they can plan around."""
        y = [1, 0, 0, 0] * 25
        scores = [0.9, 0.8, 0.7, 0.6] * 25

        result = evaluate(y, scores, list(range(100)), bootstrap=False)
        alert = next(a for a in result.alert_rates if a.alert_rate == 0.10)

        assert alert.rows_reviewed_per_event is not None
        assert alert.rows_reviewed_per_event == pytest.approx(1.0 / alert.precision)

    def test_a_ranker_that_finds_nothing_reports_zero_not_an_error(self) -> None:
        y = [0] * 95 + [1] * 5
        scores = [0.9] * 95 + [0.1] * 5

        result = evaluate(y, scores, list(range(100)), bootstrap=False)
        alert = next(a for a in result.alert_rates if a.alert_rate == 0.05)

        assert alert.events_captured == 0
        assert alert.precision == 0.0
        assert alert.rows_reviewed_per_event is None


class TestCalibration:
    def test_a_well_calibrated_model_has_slope_near_one(self) -> None:
        rng = np.random.default_rng(7)
        probabilities = rng.uniform(0.01, 0.6, size=4000)
        y = (rng.random(4000) < probabilities).astype(int).tolist()

        result = evaluate(y, probabilities.tolist(), list(range(4000)), bootstrap=False)

        assert result.calibration_slope is not None
        assert 0.85 < result.calibration_slope < 1.15

    def test_an_overconfident_model_has_slope_below_one(self) -> None:
        """Slope < 1 is the signature of predictions that are too extreme --
        the thing a report must check before quoting a probability."""
        rng = np.random.default_rng(11)
        true_probabilities = rng.uniform(0.05, 0.5, size=4000)
        y = (rng.random(4000) < true_probabilities).astype(int)
        # Push the log-odds outwards by a factor of three.
        logit = np.log(true_probabilities / (1 - true_probabilities)) * 3
        scores = 1 / (1 + np.exp(-logit))

        result = evaluate(y.tolist(), scores.tolist(), list(range(4000)), bootstrap=False)

        assert result.calibration_slope is not None
        assert result.calibration_slope < 0.7

    def test_the_curve_uses_quantile_bins_so_a_skewed_score_still_reports(self) -> None:
        scores = [0.001] * 90 + [0.5] * 10
        y = [0] * 90 + [1] * 5 + [0] * 5

        result = evaluate(y, scores, list(range(100)), bootstrap=False)

        assert len(result.calibration) >= 2


class TestGroupedBootstrap:
    def test_intervals_bracket_the_point_estimate(self) -> None:
        rng = np.random.default_rng(3)
        y = [1] * 30 + [0] * 270
        scores = rng.normal(1.0, 1.0, 30).tolist() + rng.normal(0.0, 1.0, 270).tolist()
        companies = list(range(300))

        result = evaluate(y, scores, companies, bootstrap=True)

        assert result.roc_auc_ci is not None
        assert result.roc_auc_ci[0] <= (result.roc_auc or 0) <= result.roc_auc_ci[1]

    def test_clustering_by_company_widens_the_interval(self) -> None:
        """Rows from one company are not independent draws.

        The panel this models is one where a company's ten filings share a
        label and a risk level -- so the *effective* sample size is 40
        companies, not 400 rows. Resampling rows pretends otherwise and
        reports an interval far too narrow, so the grouped one must be wider.
        (Correlation within the cluster is what makes this true; with
        genuinely independent rows the two agree, which is the correct
        behaviour and not what this test is about.)
        """
        rng = np.random.default_rng(5)
        y: list[int] = []
        scores: list[float] = []
        clustered: list[int] = []
        for company in range(40):
            failed = company < 4
            level = rng.normal(1.2 if failed else 0.0, 0.5)
            for _ in range(10):
                y.append(1 if failed else 0)
                scores.append(level + rng.normal(0, 0.1))
                clustered.append(company)

        grouped = evaluate(y, scores, clustered, bootstrap=True)
        per_row = evaluate(y, scores, list(range(len(y))), bootstrap=True)

        assert grouped.roc_auc_ci is not None
        assert per_row.roc_auc_ci is not None
        grouped_width = grouped.roc_auc_ci[1] - grouped.roc_auc_ci[0]
        per_row_width = per_row.roc_auc_ci[1] - per_row.roc_auc_ci[0]
        assert grouped_width > per_row_width

    def test_too_few_companies_reports_no_interval_rather_than_a_fake_one(self) -> None:
        y = [1, 1, 0, 0, 0, 0]
        scores = [0.9, 0.8, 0.2, 0.3, 0.1, 0.4]

        result = evaluate(y, scores, [1, 1, 2, 2, 3, 3], bootstrap=True)

        assert result.roc_auc is not None
        assert result.roc_auc_ci is None


class TestPairedComparison:
    def test_a_genuinely_better_model_has_a_positive_interval(self) -> None:
        rng = np.random.default_rng(13)
        y = np.array([1] * 60 + [0] * 540)
        noise = rng.normal(0, 1, 600)
        weak = (y * 0.3 + noise).tolist()
        strong = (y * 2.0 + noise).tolist()

        interval = delta_auc_ci(y.tolist(), weak, strong, list(range(600)))

        assert interval is not None
        point, low, high = interval
        assert point > 0
        assert low > 0

    def test_two_identical_models_have_an_interval_containing_zero(self) -> None:
        rng = np.random.default_rng(17)
        y = np.array([1] * 60 + [0] * 540)
        scores = (y * 0.8 + rng.normal(0, 1, 600)).tolist()

        interval = delta_auc_ci(y.tolist(), scores, scores, list(range(600)))

        assert interval is not None
        point, low, high = interval
        assert point == pytest.approx(0.0)
        assert low <= 0 <= high
