"""The audit trail: every version, every decision, nothing removable.

The question this page answers is the one a validator asks months later —
*what did we know, when did we know it, and who decided what?* The store is
append-only at the database level, so this page can show history without ever
having to explain why a row looks different from how it was written.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_pages import _data, _ui
from credit_risk_copilot.workspace import state_label

st.title("Audit trail", anchor=False)

if not _data.store_exists():
    st.error("No workspace database found.", icon=":material/database_off:")
    st.stop()

cik = _data.selected_cik()
if cik is None:
    st.info("Pick a company from the sidebar to see its history.", icon=":material/search:")
    st.stop()

versions = _data.history(cik)
if not versions:
    st.error("No assessments recorded for this company.", icon=":material/error:")
    st.stop()

st.subheader(versions[0].company, anchor=False)
st.caption(
    f"{len(versions)} assessment version(s). A newer filing creates a new version; "
    "earlier ones stay accessible and keep their reviews."
)

st.dataframe(
    pd.DataFrame(
        [
            {
                "As of": v.as_of,
                "Period": v.period_label or "",
                "State": state_label(v.state),
                "Current": v.is_current,
                "Watch status": v.watch_status.value if v.watch_status else "",
                "Reviews": len(v.reviews),
                "Draft": (
                    "passed"
                    if v.draft_accepted
                    else ("failed" if v.draft_accepted is False else "—")
                ),
                "Assessment ID": v.assessment_id,
            }
            for v in versions
        ]
    ),
    hide_index=True,
    width="stretch",
)

st.divider()
st.markdown("##### Decisions, oldest first")
records = [(v, r) for v in versions for r in v.reviews]
if not records:
    st.caption("No analyst decisions recorded for this company yet.")
else:
    for entry, record in sorted(records, key=lambda pair: pair[1].recorded_at):
        with st.container(border=True):
            st.markdown(
                f"**{record.decision.value.capitalize()}** by {record.analyst} · "
                + _ui.watch_badge(record.watch_status)
            )
            st.caption(
                f"on the assessment as of {entry.as_of} · recorded "
                f"{record.recorded_at.strftime('%Y-%m-%d %H:%M UTC')}"
                + (" · correction" if record.is_correction else "")
            )
            if record.comment:
                st.markdown(record.comment)
            if record.modified_text:
                st.markdown(f"> {record.modified_text}")

st.divider()
with st.expander("Pipeline versions behind the current assessment"):
    st.caption("Recorded per assessment so a stored decision can be explained years later.")
    recorded = versions[0].pipeline_versions
    if recorded:
        st.dataframe(
            pd.DataFrame({"Component": list(recorded), "Version": list(recorded.values())}),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("No component versions recorded.")
