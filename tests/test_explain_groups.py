"""Feature grouping: the map from model inputs to the analyst's vocabulary.

The grouping is what turns 97 columns into six dimensions a reader can
challenge, so a silent mis-mapping would quietly misattribute a driver to the
wrong part of the business. These tests pin the mapping against the Phase 6/7
catalogs it is derived from, rather than against a hand-written list that
could drift.
"""

from __future__ import annotations

import pytest

from credit_risk_copilot.explain.groups import (
    DIMENSIONS,
    MISSING_SUFFIX,
    MISSINGNESS_GROUP,
    base_feature,
    dimension_of,
    family_of,
    group_of,
    is_missingness_indicator,
    ratio_inputs,
)
from credit_risk_copilot.modeling.features import FEATURE_NAMES
from credit_risk_copilot.ratios.registry import RATIO_DEFINITIONS


class TestDimensions:
    def test_dimensions_come_from_the_phase6_catalog(self) -> None:
        """Not redeclared: a new ratio category must appear here automatically."""
        assert set(DIMENSIONS) == {d.category for d in RATIO_DEFINITIONS}

    @pytest.mark.parametrize("definition", RATIO_DEFINITIONS, ids=lambda d: d.ratio_id)
    def test_every_ratio_feature_inherits_its_catalog_category(self, definition) -> None:  # type: ignore[no-untyped-def]
        assert dimension_of(f"ratio_{definition.ratio_id}") == definition.category
        assert dimension_of(f"trend_pct_{definition.ratio_id}") == definition.category

    def test_signal_features_map_to_the_dimension_they_describe(self) -> None:
        assert dimension_of("signal_liquidity_deterioration") == "liquidity"
        assert dimension_of("signal_margin_compression") == "profitability"
        assert dimension_of("signal_negative_equity") == "leverage"

    def test_cross_cutting_signals_have_no_single_dimension(self) -> None:
        """`MULTI_DIMENSION_DETERIORATION` is about breadth; forcing it into one
        dimension would misstate what it means."""
        assert dimension_of("signal_multi_dimension_deterioration") is None
        assert dimension_of("signal_unusual_movement") is None

    def test_size_and_quality_features_have_no_financial_dimension(self) -> None:
        """`None` is a real answer here, not a gap -- company size is not a
        liquidity or leverage fact."""
        assert dimension_of("log_total_assets") is None
        assert dimension_of("ratio_coverage") is None


class TestMissingnessAxis:
    def test_an_indicator_is_recognised_and_stripped(self) -> None:
        assert is_missingness_indicator(f"ratio_roa{MISSING_SUFFIX}")
        assert not is_missingness_indicator("ratio_roa")
        assert base_feature(f"ratio_roa{MISSING_SUFFIX}") == "ratio_roa"

    def test_an_indicator_keeps_its_base_feature_dimension(self) -> None:
        """So an analyst can see *which* part of the picture was unavailable."""
        assert dimension_of(f"ratio_roa{MISSING_SUFFIX}") == dimension_of("ratio_roa")

    def test_but_groups_separately_from_the_value_it_is_about(self) -> None:
        """The distinction the whole missingness analysis turns on: reacting to
        leverage is not the same as reacting to leverage being unavailable."""
        assert group_of(f"ratio_debt_to_assets{MISSING_SUFFIX}") == MISSINGNESS_GROUP
        assert group_of("ratio_debt_to_assets") == "leverage"
        assert family_of(f"ratio_debt_to_assets{MISSING_SUFFIX}") == MISSINGNESS_GROUP


class TestGroupAxes:
    def test_every_model_feature_lands_in_exactly_one_group_on_each_axis(self) -> None:
        for name in FEATURE_NAMES:
            assert isinstance(group_of(name), str)
            assert isinstance(group_of(name, axis="family"), str)
            assert isinstance(group_of(f"{name}{MISSING_SUFFIX}"), str)

    def test_no_feature_falls_into_an_unknown_bucket(self) -> None:
        """A feature reaching `unknown` means the registry and the grouping
        have drifted apart, which would silently orphan a driver."""
        assert all(group_of(name, axis="family") != "unknown" for name in FEATURE_NAMES)

    def test_residual_groups_are_named_rather_than_pooled(self) -> None:
        assert group_of("log_total_assets") == "size"
        assert group_of("ratio_coverage") == "data_quality"
        assert group_of("n_deteriorating_ratios") == "cross_cutting"

    def test_an_unknown_axis_is_refused(self) -> None:
        with pytest.raises(ValueError, match="Unknown grouping axis"):
            group_of("ratio_roa", axis="sector")


class TestProvenanceHop:
    def test_a_ratio_feature_resolves_to_its_catalog_inputs(self) -> None:
        """The first hop of the chain: model feature -> canonical concepts."""
        assert ratio_inputs("ratio_debt_to_assets") == ("total_debt", "total_assets")

    def test_a_trend_feature_resolves_to_the_same_concepts_as_its_ratio(self) -> None:
        assert ratio_inputs("trend_pct_debt_to_assets") == ratio_inputs("ratio_debt_to_assets")

    def test_a_scale_feature_resolves_to_its_own_concept(self) -> None:
        assert ratio_inputs("log_total_assets") == ("total_assets",)

    def test_a_derived_level_feature_resolves_to_every_concept_behind_it(self) -> None:
        assert ratio_inputs("working_capital_to_assets") == (
            "current_assets",
            "current_liabilities",
            "total_assets",
        )

    def test_an_aggregate_resolves_to_nothing_rather_than_guessing(self) -> None:
        """`n_deteriorating_ratios` spans every ratio; pointing it at one fact
        would be a fabricated provenance link."""
        assert ratio_inputs("n_deteriorating_ratios") == ()
        assert ratio_inputs("signal_multi_dimension_deterioration") == ()

    def test_an_indicator_resolves_like_its_base_feature(self) -> None:
        assert ratio_inputs(f"ratio_debt_to_assets{MISSING_SUFFIX}") == (
            "total_debt",
            "total_assets",
        )
