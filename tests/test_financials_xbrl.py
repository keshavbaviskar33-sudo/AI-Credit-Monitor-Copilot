"""Tests for typed reading of the `companyfacts` payload (§12)."""

from __future__ import annotations

from credit_risk_copilot.financials.xbrl import facts_for_accession, index_by_concept, iter_facts

COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "end": "2024-12-31",
                            "val": 100,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-02-01",
                            "accn": "0001-25-000001",
                        },
                        {
                            "end": "2025-12-31",
                            "val": 120,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-02-01",
                            "accn": "0001-25-000001",
                        },
                        # A later filing's comparative restates the same period.
                        {
                            "end": "2025-12-31",
                            "val": 121,
                            "fy": 2026,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2026-02-01",
                            "accn": "0001-26-000002",
                        },
                    ]
                }
            },
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2025-01-01",
                            "end": "2025-12-31",
                            "val": 500,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-02-01",
                            "accn": "0001-25-000001",
                        },
                    ]
                }
            },
        },
        "acme": {  # a company extension namespace
            "CustomLeverageMetric": {
                "units": {
                    "USD": [
                        {
                            "end": "2025-12-31",
                            "val": 42,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-02-01",
                            "accn": "0001-25-000001",
                        },
                    ]
                }
            }
        },
    }
}


def test_iter_facts_covers_every_namespace() -> None:
    facts = list(iter_facts(COMPANY_FACTS))

    assert len(facts) == 5
    assert {f.namespace for f in facts} == {"us-gaap", "acme"}


def test_extension_namespace_is_flagged() -> None:
    facts = list(iter_facts(COMPANY_FACTS))
    custom = next(f for f in facts if f.concept == "CustomLeverageMetric")
    standard = next(f for f in facts if f.concept == "Revenues")

    assert custom.is_extension
    assert not standard.is_extension


def test_facts_for_accession_is_point_in_time() -> None:
    """D-008: only what *this* filing reported, including its own
    comparative column -- not a later filing's restatement of the same period."""
    facts = facts_for_accession(COMPANY_FACTS, "0001-25-000001")

    assets = [f for f in facts if f.concept == "Assets"]
    assert len(assets) == 2
    assert {f.val for f in assets} == {100, 120}


def test_facts_for_a_different_accession_sees_the_restatement() -> None:
    facts = facts_for_accession(COMPANY_FACTS, "0001-26-000002")

    assets = [f for f in facts if f.concept == "Assets"]
    assert len(assets) == 1
    assert assets[0].val == 121


def test_index_by_concept_groups_by_namespace_and_tag() -> None:
    facts = facts_for_accession(COMPANY_FACTS, "0001-25-000001")
    index = index_by_concept(facts)

    assert len(index[("us-gaap", "Assets")]) == 2
    assert len(index[("us-gaap", "Revenues")]) == 1
