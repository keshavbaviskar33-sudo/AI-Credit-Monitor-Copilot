"""Phase 8: point-in-time modelling dataset and baseline predictive model.

The layering mirrors the rest of the project -- a typed contract first, then
construction, then the model:

    labels.py     BRD events -> observable outcomes (with censoring)
    contract.py   what an observation may know, and the leakage assertions
    features.py   Phase 5/6/7 outputs -> named, provenance-carrying features
    dataset.py    the panel: companies x filings -> Observations
    splits.py     out-of-time, company-grouped evaluation folds
    model.py      the estimator, its artifact, and its metadata
    metrics.py    discrimination, calibration and alert-rate measures

Nothing here decides credit; the output is an ordered risk estimate for a
human analyst (D-003, D-010).
"""

from credit_risk_copilot.modeling.contract import (
    HorizonPolicy,
    LeakageError,
    Observation,
    ObservationKey,
    Outcome,
)
from credit_risk_copilot.modeling.labels import (
    BankruptcyCase,
    EventTable,
    load_event_table,
    measure_label_completeness,
)

__all__ = [
    "BankruptcyCase",
    "EventTable",
    "HorizonPolicy",
    "LeakageError",
    "Observation",
    "ObservationKey",
    "Outcome",
    "load_event_table",
    "measure_label_completeness",
]
