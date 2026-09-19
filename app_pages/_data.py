"""Cached data access for the workspace.

Every function opens the audit store, reads, and closes. SQLite connections
are bound to the thread that created them and Streamlit reruns on a pool, so
a long-lived connection cached with `st.cache_resource` would fail
intermittently and only under load -- the worst failure to diagnose. Opening
a file-backed SQLite database costs microseconds; correctness is cheaper than
the optimisation here.

Reads are cached on the data, writes are not cached at all, and every write
clears the caches it invalidates. The store itself refuses edits, so a stale
read can never be silently reconciled -- it has to be re-read.

Every cache is bounded. An unbounded `workspace` cache grows by one full
evidence register per company an analyst opens, and a coverage list of a few
hundred names is enough for that to matter over a long session -- so the
per-company caches keep a working set and the two whole-corpus loaders keep
exactly one entry each.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from credit_risk_copilot.review import AnalystReview, ReviewStore
from credit_risk_copilot.review.models import AssessmentHistory
from credit_risk_copilot.workspace import (
    DEFAULT_DB,
    CompanyCard,
    CompanyWorkspace,
    build_workspace,
    coverage,
    load_panel,
)

DB_PATH = Path(DEFAULT_DB)


def store_exists() -> bool:
    return DB_PATH.exists()


@st.cache_data(show_spinner=False, max_entries=1)
def panel() -> pd.DataFrame:
    """The Phase 8 point-in-time panel: multi-year ratio history."""
    return load_panel()


@st.cache_data(show_spinner="Reading the audit store…", max_entries=1)
def cards() -> tuple[CompanyCard, ...]:
    with ReviewStore(DB_PATH) as store:
        return coverage(store, panel())


@st.cache_data(show_spinner=False, max_entries=64)
def history(cik: int) -> tuple[AssessmentHistory, ...]:
    with ReviewStore(DB_PATH) as store:
        return store.history(cik)


@st.cache_data(show_spinner="Assembling the workspace…", max_entries=16)
def workspace(assessment_id: str, cik: int) -> CompanyWorkspace | None:
    with ReviewStore(DB_PATH) as store:
        for entry in store.history(cik):
            if entry.assessment_id == assessment_id:
                return build_workspace(store, entry, panel())
    return None


def record_review(review: AnalystReview) -> None:
    """Write a decision and drop every cached read it invalidates."""
    with ReviewStore(DB_PATH) as store:
        store.record_review(review)
    cards.clear()
    history.clear()
    workspace.clear()


def company_index() -> dict[int, str]:
    return {card.cik: card.company for card in cards()}


def company_url(cik: int) -> str:
    """A deep link to one company's workspace.

    Ordinary navigation, so it cannot half-work the way a programmatic page
    switch can -- and the resulting URL is bookmarkable, which a callback
    never is.
    """
    return f"/company?cik={cik}"


def selected_cik() -> int | None:
    """The company in view: the URL wins, session state is the fallback.

    The query parameter is authoritative so that a pasted or reloaded link
    always lands on the company it names. Session state carries the selection
    between pages that have no parameter of their own, such as the audit
    trail.
    """
    raw = st.query_params.get("cik")
    if raw is not None:
        try:
            cik = int(raw)
        except ValueError:
            return st.session_state.get("cik")
        if cik != st.session_state.get("cik"):
            st.session_state["cik"] = cik
            st.session_state["assessment_id"] = None
        return cik
    return st.session_state.get("cik")
