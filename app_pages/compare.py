"""Comparison across companies under coverage.

**Not** peer benchmarking, and the page says so. Peer analysis needs an
industry classification and a comparable set, and this system has neither: the
universe is filtered for scope, not grouped by sector, and no benchmark series
exists anywhere in the pipeline. Presenting these columns as "peers" would be
the most quietly misleading thing the UI could do.

What it is instead is genuinely useful: the same measured columns, for
companies *you cover*, at each one's own as-of date. Every cell traces to an
assessment.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app_pages import _data
from credit_risk_copilot.assessment.models import LayerId
from credit_risk_copilot.workspace import CONCERN_LABELS

st.title("Compare", anchor=False)
st.caption(
    "Companies under coverage, side by side. Not a peer group — no sector "
    "benchmark exists in this system."
)

if not _data.store_exists():
    st.error("No workspace database found.", icon=":material/database_off:")
    st.stop()

cards = _data.cards()
index = {c.cik: c.company for c in cards}
by_cik = {c.cik: c for c in cards}

picked = st.multiselect(
    "Companies",
    sorted(index, key=lambda cik: index[cik]),
    default=[c.cik for c in cards if len(c.elevated_layers) == 3][:4],
    format_func=lambda cik: index[cik],
    max_selections=8,
    key="compare_pick",
)

if not picked:
    st.info("Pick up to eight companies to compare.", icon=":material/compare_arrows:")
    st.stop()

RATIO_COLUMNS = (
    ("current_ratio", "Current ratio"),
    ("debt_to_equity", "Debt / equity"),
    ("liabilities_to_assets", "Liabilities / assets"),
    ("interest_coverage", "Interest coverage"),
    ("net_profit_margin", "Net margin"),
    ("ocf_to_debt", "OCF / debt"),
)

rows = []
for cik in picked:
    card = by_cik[cik]
    workspace = _data.workspace(card.assessment_id, cik)
    if workspace is None:
        continue
    ratios = {r.ratio_id: r.latest for r in workspace.ratios}
    health = card.read(LayerId.FINANCIAL_HEALTH)
    narrative = card.read(LayerId.NARRATIVE)
    row = {
        "Company": card.company,
        "As of": card.as_of.isoformat(),
        "Trends": CONCERN_LABELS[health.concern] if health else "",
        "Model percentile": workspace.score_percentile,
        "Filing language": CONCERN_LABELS[narrative.concern] if narrative else "",
        "Disagreements": card.n_contradictions,
    }
    row.update({label: ratios.get(key) for key, label in RATIO_COLUMNS})
    rows.append(row)

frame = pd.DataFrame(rows).set_index("Company")
st.dataframe(
    frame,
    width="stretch",
    column_config={
        "Model percentile": st.column_config.ProgressColumn(
            "Model percentile",
            help="Position within the same scoring year. Not a probability.",
            format="%.0f",
            min_value=0,
            max_value=100,
        ),
        "Current ratio": st.column_config.NumberColumn(format="%.2f"),
        "Debt / equity": st.column_config.NumberColumn(format="%.2f"),
        "Liabilities / assets": st.column_config.NumberColumn(format="%.2f"),
        "Interest coverage": st.column_config.NumberColumn(format="%.2f"),
        "Net margin": st.column_config.NumberColumn(format="%.3f"),
        "OCF / debt": st.column_config.NumberColumn(format="%.3f"),
    },
)

st.caption(
    "Each row is that company's own latest assessment, at its own as-of date. "
    "Blank cells are ratios that were not computable from the filings available "
    "then — never zero, never imputed."
)

st.divider()
st.markdown("##### Ratio trends, overlaid")
ratio_choice = st.selectbox(
    "Ratio",
    RATIO_COLUMNS,
    format_func=lambda pair: pair[1],
    key="compare_ratio",
)

series_rows = []
for cik in picked:
    card = by_cik[cik]
    workspace = _data.workspace(card.assessment_id, cik)
    if workspace is None:
        continue
    series = next((r for r in workspace.ratios if r.ratio_id == ratio_choice[0]), None)
    if series is None:
        continue
    for point in series.observed:
        series_rows.append({"Company": card.company, "Period": point.period, "Value": point.value})

if series_rows:
    chart_frame = pd.DataFrame(series_rows)
    chart = (
        alt.Chart(chart_frame)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("Period:O", title=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Value:Q", title=ratio_choice[1], scale=alt.Scale(zero=False)),
            color=alt.Color("Company:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Company", "Period", alt.Tooltip("Value:Q", format=",.3f")],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, width="stretch")
    st.caption(
        "Periods are each company's own fiscal labels; companies with different "
        "year-ends are not aligned to a common calendar."
    )
else:
    st.caption("No point-in-time history available for the selected ratio.")
