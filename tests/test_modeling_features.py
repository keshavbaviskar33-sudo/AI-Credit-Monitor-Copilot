"""Feature construction: registry integrity, missingness semantics, pathologies.

The rule under test throughout is §15's: `None` means *not computable* and
must survive as `None`. A credit model that reads "we could not compute
leverage" as "leverage is zero" is worse than one with no leverage feature at
all, because the failure is invisible.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from credit_risk_copilot.financials.history import resolve_company_history
from credit_risk_copilot.health import analyze_financial_health
from credit_risk_copilot.modeling.features import (
    FAMILY_ORDER,
    FEATURE_NAMES,
    FEATURE_SPECS,
    SPECS_BY_NAME,
    build_features,
    feature_names_for_families,
)
from credit_risk_copilot.modeling.model import design_matrix
from credit_risk_copilot.ratios.engine import ratios_from_facts
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS
from tests._modeling_helpers import company_facts, declining_company, filing, filing_refs


def _features_from(facts_payload: dict, refs: list) -> dict[str, float | None]:  # type: ignore[type-arg]
    history = resolve_company_history(facts_payload, refs, cik=1, company="Test Co")
    facts = history.financials.as_of(date(2100, 1, 1))
    periods = sorted({period for _, period in facts})
    ratio_history = ratios_from_facts(facts, periods)
    report = analyze_financial_health("Test Co", ratio_history)
    return build_features(
        facts=facts,
        period_label=report.period_label,
        ratio_history=ratio_history,
        report=report,
    )


class TestRegistry:
    def test_every_feature_name_is_unique(self) -> None:
        assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))

    def test_every_spec_belongs_to_a_declared_family(self) -> None:
        assert {spec.family for spec in FEATURE_SPECS} == set(FAMILY_ORDER)

    def test_every_catalog_ratio_has_a_level_and_a_trend_feature(self) -> None:
        """The ablation only means something if the ratio and trend families
        actually cover the Phase 6 catalog -- a silently missing ratio would
        understate what Phase 6 contributes."""
        for definition in RATIO_DEFINITIONS:
            assert f"ratio_{definition.ratio_id}" in SPECS_BY_NAME
            assert f"trend_pct_{definition.ratio_id}" in SPECS_BY_NAME

    def test_families_stack_cumulatively_in_the_ablation(self) -> None:
        sizes = [len(feature_names_for_families(FAMILY_ORDER[:n])) for n in range(1, 7)]

        assert sizes == sorted(sizes)
        assert sizes[-1] == len(FEATURE_NAMES)

    def test_provenance_source_is_recorded_for_ratio_and_signal_features(self) -> None:
        """§14: a feature must be traceable back to the concept, ratio or
        signal it came from."""
        assert SPECS_BY_NAME["ratio_current_ratio"].source_id == "current_ratio"
        assert SPECS_BY_NAME["ratio_current_ratio"].source_kind == "ratio"
        assert SPECS_BY_NAME["signal_negative_equity"].source_id == "negative_equity"
        assert SPECS_BY_NAME["log_total_assets"].source_id == "total_assets"


class TestValues:
    def test_a_complete_company_produces_every_feature(self) -> None:
        facts, refs = declining_company()

        features = _features_from(facts, refs)

        assert set(features) == set(FEATURE_NAMES)
        assert all(value is not None for value in features.values())

    def test_features_are_deterministic_across_runs(self) -> None:
        facts, refs = declining_company()

        assert _features_from(facts, refs) == _features_from(facts, refs)


class TestMissingness:
    def _no_cash_flow_statement(self) -> tuple[dict, list]:  # type: ignore[type-arg]
        """A filer that tags no cash-flow statement at all. Every cash-flow
        ratio and level must become `None`, not 0."""
        filings = []
        for year in (2019, 2020):
            contribution = filing(
                accession=f"0000000000-{str(year + 1)[2:]}-000001",
                filed=f"{year + 1}-03-01",
                period_end=f"{year}-12-31",
                years=dict.fromkeys(range(2018, year + 1), 1.0),
            )
            for tag in (
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInInvestingActivities",
                "NetCashProvidedByUsedInFinancingActivities",
                "PaymentsToAcquirePropertyPlantAndEquipment",
            ):
                contribution["entries"].pop(tag, None)
            filings.append(contribution)
        return company_facts(*filings), filing_refs(*filings)

    def test_an_absent_statement_yields_none_never_zero(self) -> None:
        facts, refs = self._no_cash_flow_statement()

        features = _features_from(facts, refs)

        assert features["fcf_to_assets"] is None
        assert features["ratio_ocf_to_debt"] is None
        assert features["ratio_ocf_to_revenue"] is None
        assert features["retained_cash_flow_to_debt"] is None

    def test_missingness_is_visible_in_the_quality_family(self) -> None:
        """A model that cannot see the ratio is at least told that coverage
        dropped -- the distinction between a weak company and an unreadable
        one."""
        complete, complete_refs = declining_company()
        sparse, sparse_refs = self._no_cash_flow_statement()

        assert _features_from(sparse, sparse_refs)["ratio_coverage"] < (
            _features_from(complete, complete_refs)["ratio_coverage"] or 0.0
        )

    def test_design_matrix_turns_none_into_nan_not_zero(self) -> None:
        """The boundary where a `None` could silently become a number."""
        facts, refs = self._no_cash_flow_statement()
        features = _features_from(facts, refs)

        class _Row:
            def __init__(self, values: dict[str, float | None]) -> None:
                self.features = values

        matrix, names = design_matrix(
            [_Row(features)],  # type: ignore[list-item]
            ("fcf_to_assets", "log_total_assets"),
            add_missing_indicators=False,
        )

        assert np.isnan(matrix[0][0])
        assert not np.isnan(matrix[0][1])
        assert names == ["fcf_to_assets", "log_total_assets"]

    def test_missing_indicators_are_added_only_where_something_is_missing(self) -> None:
        class _Row:
            def __init__(self, values: dict[str, float | None]) -> None:
                self.features = values

        rows = [
            _Row({"a": 1.0, "b": None}),
            _Row({"a": 2.0, "b": 3.0}),
        ]

        matrix, names = design_matrix(
            rows,  # type: ignore[arg-type]
            ("a", "b"),
            add_missing_indicators=True,
        )

        assert names == ["a", "b", "b__missing"]
        assert matrix[:, 2].tolist() == [1.0, 0.0]


class TestPathologicalValues:
    def test_negative_equity_is_kept_as_a_signal_not_discarded(self) -> None:
        """Negative equity is genuine distress, not a data error (§16). The
        ratio it breaks becomes unavailable, but the *fact* of it must reach
        the model."""
        filings = []
        for year in (2019, 2020):
            filings.append(
                filing(
                    accession=f"0000000000-{str(year + 1)[2:]}-000001",
                    filed=f"{year + 1}-03-01",
                    period_end=f"{year}-12-31",
                    years=dict.fromkeys(range(2018, year + 1), 1.0),
                    overrides={(y, "StockholdersEquity"): -200.0 for y in range(2018, year + 1)}
                    | {(y, "Liabilities"): 1200.0 for y in range(2018, year + 1)},
                )
            )

        features = _features_from(company_facts(*filings), filing_refs(*filings))

        assert features["signal_negative_equity"] == 1.0
        assert features["ratio_debt_to_assets"] is not None

    def test_a_zero_denominator_yields_none_rather_than_an_infinity(self) -> None:
        filings = []
        for year in (2019, 2020):
            filings.append(
                filing(
                    accession=f"0000000000-{str(year + 1)[2:]}-000001",
                    filed=f"{year + 1}-03-01",
                    period_end=f"{year}-12-31",
                    years=dict.fromkeys(range(2018, year + 1), 1.0),
                    overrides={(y, "Assets"): 0.0 for y in range(2018, year + 1)},
                )
            )

        features = _features_from(company_facts(*filings), filing_refs(*filings))

        assert features["log_total_assets"] is None
        assert features["working_capital_to_assets"] is None
        assert all(
            value is None or np.isfinite(value) for value in features.values() if value is not None
        )
