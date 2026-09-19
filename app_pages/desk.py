"""The desk: what needs an analyst today, and why.

Deliberately **not** a wall of KPI cards, and deliberately not a ranked queue.

A priority ranking needs a severity number, and this system does not produce
one -- four decisions refused it, and inventing one here would be that score
arriving at last, disguised as a sort order. So the desk groups by *reason*
instead. A company appears under every named reason that applies to it, each
reason is a checkable fact about the assessment, and the analyst decides which
matters this morning.

That is also better UX than a ranking. "Top of the queue" tells you nothing;
"the filer states going-concern doubt" tells you what to open next.
"""

from __future__ import annotations

import streamlit as st

from app_pages import _data, _ui
from credit_risk_copilot.workspace import (
    ATTENTION_EXPLANATIONS,
    group_by_attention,
)

st.title("Desk", anchor=False)

if not _data.store_exists():
    st.error(
        "No workspace database found. Build one with "
        "`uv run python scripts/build_workspace_db.py`.",
        icon=":material/database_off:",
    )
    st.stop()

cards = _data.cards()
buckets = group_by_attention(cards)

st.caption(
    f"{len(cards)} companies under coverage · assessments are point-in-time, "
    "each fixed to the filings available on its as-of date"
)

# --- the one honest summary row -------------------------------------------
# Counts, not scores. Each number is how many companies match a checkable
# condition, and each is clickable context for the sections below.
summary = st.columns(4, gap="medium")
all_three = len([c for c in cards if len(c.elevated_layers) == 3])
disagreeing = len([c for c in cards if c.n_contradictions])
unreviewed = len([c for c in cards if c.state.value == "draft"])
unread = len([c for c in cards if "Filing sections unread" in c.attention])

for column, (label, value, caption) in zip(
    summary,
    (
        ("All three layers elevated", all_three, "independent methods agreeing"),
        ("Layers disagree", disagreeing, "a human has to resolve it"),
        ("Awaiting review", unreviewed, "no analyst decision recorded"),
        ("Sections unread", unread, "absence of signal is partly absence of reading"),
    ),
    strict=False,
):
    with column, st.container(border=True):
        st.caption(label)
        st.markdown(f"## {_ui.num(str(value))}")
        st.caption(caption)

st.divider()

if not buckets:
    st.success("Nothing on the desk.", icon=":material/check_circle:")
    st.stop()

tab_labels = [f"{reason} ({len(items)})" for reason, items in buckets.items()]

for tab, (reason, items) in zip(st.tabs(tab_labels), buckets.items(), strict=False):
    with tab:
        st.caption(ATTENTION_EXPLANATIONS[reason])
        for card in items:
            _ui.company_row(card, url=_data.company_url(card.cik))

st.divider()
with st.expander("Why this page has no priority ranking"):
    st.markdown(
        """
Ranking companies against each other needs a single severity number, and this
system does not produce one. The predictive model outputs a **position in a
ranking of its own scoring year**, which is not comparable across years and is
explicitly not a probability. The trend layer reports **per-dimension
directions** and refuses to average them. The narrative layer reports **what a
filer stated**, with measured specificity per disclosure code.

Collapsing those three into one number would discard exactly the information
that makes them worth having — most of all their disagreements, which are the
only finding here that no single layer produces.

So the desk names reasons instead. Every company on this page is here because
a specific, checkable condition holds, and the condition is written above each
list.
        """
    )
