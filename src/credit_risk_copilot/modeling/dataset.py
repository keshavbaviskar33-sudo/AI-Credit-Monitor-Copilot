"""Building the panel: companies x filings -> leakage-checked `Observation`s.

This is the module that actually enforces the point-in-time contract, and it
does so structurally rather than by care:

1. For each company, list its annual filings once.
2. For each filing, take its `filed` date as the information cutoff **T**.
3. Re-resolve the company's history with `filed_on_or_before=T`, so filings
   after T are never loaded, never resolved, and cannot contribute a fact.
4. Take `as_of(T)`, which keeps the earliest-filed value for every
   (concept, period) -- the as-filed figure, not a later restatement (D-008).
5. Run Phase 6 and Phase 7 over exactly that view.
6. Label from the event table, which censors anything unobservable.
7. Assert, for every row, that each contributing accession really was filed on
   or before T -- then emit it.

Step 7 is not decoration. Steps 3 and 4 are *claims* about how the builder was
written; step 7 is a *check* on the object that was built, and it is the only
thing standing between a subtle ordering bug and a silently optimistic model.

## Why observations are re-resolved per filing rather than resolved once

Resolving each company once and slicing afterwards would be far cheaper, and
it is exactly the shortcut that produces leakage: the slice would have to
filter facts by their filing date *after* the resolver had already used every
filing to decide conflicts, derivations and period sets. A `total_liabilities`
derived at a fixpoint that consumed a 2024 filing is contaminated even if the
final fact's own provenance points at a 2019 accession. Re-resolving is
O(filings^2) per company and measurably slower; correctness is worth it, and
the cost is bounded because a company has tens of filings, not thousands.

## Cost control

The one concession to cost: `resolve_filing` is memoised per
(accession, period_end) inside a build, because the same filing is re-resolved
at every later cutoff and its output depends only on its own accession. That
is a pure-function cache, not a relaxation of the rule above -- the *set* of
filings fed to `CompanyFinancials` still changes with every cutoff.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from credit_risk_copilot.financials.company import CompanyFinancials
from credit_risk_copilot.financials.history import FilingRefLike, accessions_with_facts
from credit_risk_copilot.financials.models import CanonicalFact, CanonicalFilingFacts
from credit_risk_copilot.financials.resolver import resolve_filing
from credit_risk_copilot.health import analyze_financial_health
from credit_risk_copilot.health.thresholds import DEFAULT_ANALYSIS_WINDOW
from credit_risk_copilot.modeling.contract import (
    HorizonPolicy,
    Observation,
    ObservationKey,
    Outcome,
)
from credit_risk_copilot.modeling.features import build_features
from credit_risk_copilot.modeling.labels import EventTable
from credit_risk_copilot.ratios.engine import ratios_from_facts
from credit_risk_copilot.ratios.models import RatioResult

logger = logging.getLogger(__name__)

#: Fiscal periods a company must have resolved, as of the cutoff, before an
#: observation is emitted at all. One period yields no trend, no change and no
#: Phase 7 content -- the row would be a ratio snapshot masquerading as a
#: monitoring observation.
MIN_PERIODS_FOR_OBSERVATION = 2


class SkippedObservation(BaseModel):
    """A filing that produced no usable row, and why."""

    model_config = ConfigDict(frozen=True)

    cik: int
    accession: str
    prediction_date: date
    reason_code: str
    message: str


class PanelBuildResult(BaseModel):
    """Every observation built, plus the funnel that produced them."""

    model_config = ConfigDict(frozen=True)

    observations: tuple[Observation, ...]
    skipped: tuple[SkippedObservation, ...]
    horizon: HorizonPolicy
    analysis_window: int | None

    def usable(self) -> tuple[Observation, ...]:
        return tuple(obs for obs in self.observations if obs.outcome.is_usable)

    def skip_reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.skipped:
            counts[entry.reason_code] = counts.get(entry.reason_code, 0) + 1
        return dict(sorted(counts.items()))


class _FilingResolver:
    """Memoised `resolve_filing` for one company within one build."""

    def __init__(self, company_facts: dict[str, Any], cik: int, company: str) -> None:
        self._company_facts = company_facts
        self._cik = cik
        self._company = company
        self._cache: dict[str, CanonicalFilingFacts | None] = {}
        self._available = accessions_with_facts(company_facts)

    def resolve(self, ref: FilingRefLike) -> CanonicalFilingFacts | None:
        if ref.accession in self._cache:
            return self._cache[ref.accession]
        resolved: CanonicalFilingFacts | None = None
        if ref.accession in self._available and ref.period:
            try:
                resolved = resolve_filing(
                    self._company_facts,
                    cik=self._cik,
                    company=self._company,
                    accession=ref.accession,
                    form=ref.form,
                    filed=ref.filed,
                    period_end=ref.period,
                )
            except (ValueError, KeyError, TypeError) as exc:
                logger.debug("CIK%d %s: resolver error %s", self._cik, ref.accession, exc)
                resolved = None
            if resolved is not None and not resolved.period_labels:
                resolved = None
        self._cache[ref.accession] = resolved
        return resolved


def build_company_observations(
    *,
    company_facts: dict[str, Any],
    filings: Sequence[FilingRefLike],
    cik: int,
    company: str,
    events: EventTable,
    horizon: HorizonPolicy,
    analysis_window: int | None = DEFAULT_ANALYSIS_WINDOW,
) -> tuple[list[Observation], list[SkippedObservation]]:
    """One company's observations, one per annual filing that supports a row."""
    resolver = _FilingResolver(company_facts, cik, company)
    ordered = sorted(filings, key=lambda ref: (ref.filed, ref.accession))
    filing_dates = {ref.accession: date.fromisoformat(ref.filed) for ref in ordered}

    observations: list[Observation] = []
    skipped: list[SkippedObservation] = []

    for index, trigger in enumerate(ordered):
        cutoff = filing_dates[trigger.accession]

        # Everything filed on or before the cutoff -- including the trigger
        # itself, which is the new information this observation exists to
        # react to. Slicing by index rather than re-filtering by date keeps
        # same-day filings deterministic.
        visible = ordered[: index + 1]
        resolved = [filing for ref in visible if (filing := resolver.resolve(ref)) is not None]
        if not resolved:
            skipped.append(
                _skip(cik, trigger, cutoff, "no_resolved_filings", "No visible filing resolved.")
            )
            continue

        financials = CompanyFinancials(cik=cik, company=company, filings=tuple(resolved))
        facts = financials.as_of(cutoff)
        if not facts:
            skipped.append(
                _skip(cik, trigger, cutoff, "no_facts_as_of", "as_of returned no resolved facts.")
            )
            continue

        periods = sorted({period for _, period in facts}, key=_fiscal_year)
        if len(periods) < MIN_PERIODS_FOR_OBSERVATION:
            skipped.append(
                _skip(
                    cik,
                    trigger,
                    cutoff,
                    "too_few_periods",
                    f"Only {len(periods)} fiscal period(s) visible at the cutoff.",
                )
            )
            continue

        ratio_history = ratios_from_facts(facts, periods)
        report = analyze_financial_health(company, ratio_history, analysis_window=analysis_window)
        latest_period = report.period_label or periods[-1]

        outcome = events.outcome(cik, cutoff, horizon)
        features = build_features(
            facts=facts,
            period_label=latest_period,
            ratio_history=ratio_history,
            report=report,
        )

        key = ObservationKey(
            cik=cik,
            company=company,
            prediction_date=cutoff,
            information_cutoff=cutoff,
            source_accession=trigger.accession,
            source_form=trigger.form,
            fiscal_period_label=latest_period,
            contributing_accessions=_contributing(facts, latest_period, ratio_history),
        )
        observation = Observation(key=key, features=features, outcome=outcome)
        # The check, not the claim. Raises rather than logs: a leaking row
        # must never reach a model.
        observation.assert_no_future_information(filing_dates)
        observations.append(observation)

    return observations, skipped


def _contributing(
    facts: dict[tuple[str, str], CanonicalFact],
    latest_period: str,
    ratio_history: dict[str, tuple[RatioResult, ...]],
) -> tuple[str, ...]:
    """Every accession whose facts reached this row, from the facts' own
    provenance -- read off `CanonicalFact.provenance`, never assumed from the
    filing list, so a derived fact reports the accessions of all its inputs."""
    accessions: set[str] = set()
    periods_used = {r.period_label for results in ratio_history.values() for r in results}
    periods_used.add(latest_period)
    for (_, period_label), fact in facts.items():
        if period_label not in periods_used:
            continue
        for provenance in fact.provenance:
            if provenance.accession:
                accessions.add(provenance.accession)
    return tuple(sorted(accessions))


def _skip(
    cik: int, ref: FilingRefLike, cutoff: date, code: str, message: str
) -> SkippedObservation:
    return SkippedObservation(
        cik=cik,
        accession=ref.accession,
        prediction_date=cutoff,
        reason_code=code,
        message=message,
    )


def _fiscal_year(period_label: str) -> int:
    digits = "".join(ch for ch in period_label if ch.isdigit())
    return int(digits[:4]) if len(digits) >= 4 else 0


def build_panel(
    companies: Iterable[tuple[dict[str, Any], Sequence[FilingRefLike], int, str]],
    *,
    events: EventTable,
    horizon: HorizonPolicy,
    analysis_window: int | None = DEFAULT_ANALYSIS_WINDOW,
) -> PanelBuildResult:
    """Build the whole panel from an iterable of per-company inputs."""
    observations: list[Observation] = []
    skipped: list[SkippedObservation] = []

    for company_facts, filings, cik, company in companies:
        company_observations, company_skipped = build_company_observations(
            company_facts=company_facts,
            filings=filings,
            cik=cik,
            company=company,
            events=events,
            horizon=horizon,
            analysis_window=analysis_window,
        )
        observations.extend(company_observations)
        skipped.extend(company_skipped)

    return PanelBuildResult(
        observations=tuple(observations),
        skipped=tuple(skipped),
        horizon=horizon,
        analysis_window=analysis_window,
    )


def relabel(
    observations: Sequence[Observation], events: EventTable, horizon: HorizonPolicy
) -> tuple[Observation, ...]:
    """Re-derive every outcome under a different horizon, reusing the features.

    Features depend only on the information cutoff, never on the horizon, so a
    second horizon needs no re-resolution -- which matters, because building
    the panel is dominated by re-resolving filings. The keys (and therefore
    the leakage guarantees already asserted on them) are carried over
    untouched.
    """
    return tuple(
        Observation(
            key=observation.key,
            features=observation.features,
            outcome=events.outcome(observation.key.cik, observation.key.prediction_date, horizon),
        )
        for observation in observations
    )


def outcome_counts(observations: Sequence[Observation]) -> dict[str, int]:
    counts = {"positive": 0, "negative": 0, "censored": 0}
    for observation in observations:
        label = observation.outcome.label
        if label == 1:
            counts["positive"] += 1
        elif label == 0:
            counts["negative"] += 1
        else:
            counts["censored"] += 1
    return counts


def censoring_reasons(observations: Sequence[Observation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for observation in observations:
        reason = observation.outcome.censoring_reason
        if reason is None:
            continue
        key = reason.split(" at the prediction date")[0].split(", after the event source")[0]
        key = "active_proceeding" if key.startswith("Company was inside") else "horizon_unobserved"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


#: Row keys that identify or label an observation rather than describe it.
#: Everything else in a row emitted by `as_rows` is a feature.
NON_FEATURE_COLUMNS: frozenset[str] = frozenset(
    {
        "cik",
        "company",
        "prediction_date",
        "source_accession",
        "source_form",
        "fiscal_period_label",
        "n_contributing_accessions",
        "label",
        "horizon_end",
        "event_date",
        "days_to_event",
        "censoring_reason",
    }
)


def observations_from_rows(rows: Sequence[dict[str, Any]]) -> tuple[Observation, ...]:
    """Rebuild observations from the flat rows `as_rows` produced.

    The round trip drops `contributing_accessions` -- it is written as a count,
    not a list -- so a rebuilt observation cannot re-run
    `assert_no_future_information`. That is deliberate rather than an
    oversight: the leakage assertion belongs at *build* time, where the filing
    dates are known, and re-asserting it downstream from a CSV would only
    check the CSV against itself. The training script reads rebuilt rows; the
    guarantee they carry was established when they were written.
    """
    rebuilt: list[Observation] = []
    for row in rows:
        prediction_date = _as_date(row["prediction_date"])
        label_value = row.get("label")
        label = None if label_value is None or _is_nan(label_value) else int(label_value)
        event_date = _as_date(row.get("event_date")) if row.get("event_date") else None
        censoring_reason = row.get("censoring_reason")
        if label is not None:
            censoring_reason = None
        elif not censoring_reason or _is_nan(censoring_reason):
            censoring_reason = "Censored (reason not preserved in the flat row)."
        rebuilt.append(
            Observation(
                key=ObservationKey(
                    cik=int(row["cik"]),
                    company=str(row["company"]),
                    prediction_date=prediction_date,
                    information_cutoff=prediction_date,
                    source_accession=str(row["source_accession"]),
                    source_form=str(row["source_form"]),
                    fiscal_period_label=str(row["fiscal_period_label"]),
                ),
                features={
                    key: (None if value is None or _is_nan(value) else float(value))
                    for key, value in row.items()
                    if key not in NON_FEATURE_COLUMNS
                },
                outcome=Outcome(
                    label=label,
                    horizon_end=_as_date(row["horizon_end"]),
                    event_date=event_date if label == 1 else None,
                    days_to_event=(
                        int(row["days_to_event"])
                        if label == 1 and not _is_nan(row.get("days_to_event"))
                        else None
                    ),
                    censoring_reason=censoring_reason,
                ),
            )
        )
    return tuple(rebuilt)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and value != value


def as_rows(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    """Flatten observations into plain dicts for CSV/DataFrame output."""
    rows: list[dict[str, Any]] = []
    for observation in observations:
        row: dict[str, Any] = {
            "cik": observation.key.cik,
            "company": observation.key.company,
            "prediction_date": observation.key.prediction_date.isoformat(),
            "source_accession": observation.key.source_accession,
            "source_form": observation.key.source_form,
            "fiscal_period_label": observation.key.fiscal_period_label,
            "n_contributing_accessions": len(observation.key.contributing_accessions),
            "label": observation.outcome.label,
            "horizon_end": observation.outcome.horizon_end.isoformat(),
            "event_date": (
                observation.outcome.event_date.isoformat()
                if observation.outcome.event_date
                else None
            ),
            "days_to_event": observation.outcome.days_to_event,
            "censoring_reason": observation.outcome.censoring_reason,
        }
        row.update(observation.features)
        rows.append(row)
    return rows
