"""Shared renderers for the analyst workspace.

Streamlit lives here and in the page files; every decision about *what* to
show is in `credit_risk_copilot.workspace`. These functions turn a view model
into pixels and do no derivation of their own.

Two conventions run through all of them.

**Figures render in monospace.** Wrapping a number in backticks puts it in the
theme's code font (JetBrains Mono), so columns of ratios line up digit for
digit. This is done through Markdown rather than CSS, which means it survives
theme changes and works identically in light and dark mode.

**A state is never colour alone.** Every concern badge carries an icon, a
word and a colour, in that order of importance. An analyst with a red-green
deficiency, a bad monitor or a printout loses the colour and keeps the meaning.
"""

from __future__ import annotations

from collections.abc import Sequence

import altair as alt
import pandas as pd
import streamlit as st

from credit_risk_copilot.assessment.models import Concern, EvidenceItem
from credit_risk_copilot.review.models import AssessmentState, CreditWatchStatus
from credit_risk_copilot.workspace import (
    CONCERN_COLORS,
    CONCERN_ICONS,
    CONCERN_LABELS,
    CompanyCard,
    DriverBar,
    LayerRead,
    RatioSeries,
    format_currency,
    format_percent,
    format_ratio,
    state_label,
)

WATCH_COLORS: dict[CreditWatchStatus, str] = {
    CreditWatchStatus.STABLE: "green",
    CreditWatchStatus.MONITOR: "blue",
    CreditWatchStatus.WATCHLIST: "orange",
    CreditWatchStatus.ESCALATE: "red",
}

STATE_COLORS: dict[AssessmentState, str] = {
    AssessmentState.DRAFT: "gray",
    AssessmentState.APPROVED: "green",
    AssessmentState.MODIFIED: "violet",
    AssessmentState.REJECTED: "red",
    AssessmentState.SUPERSEDED: "gray",
}


def num(value: str) -> str:
    """A figure, in the monospace data face."""
    return f"`{value}`"


def concern_badge(concern: Concern) -> str:
    return f":{CONCERN_COLORS[concern]}-badge[{CONCERN_ICONS[concern]} {CONCERN_LABELS[concern]}]"


def watch_badge(status: CreditWatchStatus | None) -> str:
    if status is None:
        return ":gray-badge[:material/radio_button_unchecked: No analyst standing]"
    return f":{WATCH_COLORS[status]}-badge[:material/flag: {status.value.capitalize()}]"


def state_badge(state: AssessmentState) -> str:
    return f":{STATE_COLORS[state]}-badge[{state_label(state)}]"


def section(title: str, caption: str | None = None) -> None:
    """A section heading with the question it answers."""
    st.subheader(title, anchor=False)
    if caption:
        st.caption(caption)


def read_panel(read: LayerRead, *, on_evidence=None) -> None:
    """One of the three reads, as a bordered column.

    The method line is always visible. An analyst comparing three verdicts
    needs to know that one is a ratio calculation, one is a fitted model and
    one is a regex over English -- their failure modes are unrelated, and that
    is the whole reason the three are shown side by side rather than merged.
    """
    with st.container(border=True, height=230):
        st.markdown(f"**{read.title}**")
        st.caption(read.method)
        if not read.available:
            st.markdown(":gray-badge[:material/block: Did not run]")
            st.caption(read.unavailable_reason or "No evidence produced.")
            return
        st.markdown(concern_badge(read.concern))
        st.markdown(f"**{read.headline}**")
        st.caption(read.detail)
        if read.evidence_ids and on_evidence is not None:
            st.caption(f"{len(read.evidence_ids)} evidence item(s)")


def three_reads_row(card: CompanyCard) -> None:
    columns = st.columns(3, gap="small")
    for column, read in zip(columns, card.reads, strict=False):
        with column:
            read_panel(read, on_evidence=True)


def attention_pills(card: CompanyCard) -> str:
    if not card.attention:
        return ":green-badge[:material/check: Nothing flagged]"
    return " ".join(f":orange-badge[{reason}]" for reason in card.attention)


def evidence_table(items: Sequence[EvidenceItem]) -> pd.DataFrame:
    """The evidence register as a scannable frame."""
    return pd.DataFrame(
        [
            {
                "ID": item.evidence_id,
                "Layer": item.layer.value.replace("_", " "),
                "Kind": item.kind.value.replace("_", " "),
                "Dimension": item.dimension or "",
                "Read": CONCERN_LABELS[item.concern],
                "Statement": item.summary,
                "Period": item.period_label or "",
                "Filed": item.filed.isoformat() if item.filed else "",
                "Filing": item.accession or "",
            }
            for item in items
        ]
    )


def evidence_detail(item: EvidenceItem) -> None:
    """One evidence item, opened. The bottom of every drill-down."""
    st.markdown(f"**{item.evidence_id}** · {concern_badge(item.concern)}")
    st.markdown(item.summary)
    if item.quote:
        st.caption("Verbatim from the filing — character for character")
        st.markdown(f"> {item.quote}")
    facts = {
        "Layer": item.layer.value.replace("_", " "),
        "Kind": item.kind.value.replace("_", " "),
        "Dimension": item.dimension or "—",
        "Fiscal period": item.period_label or "—",
        "Accession": item.accession or "—",
        "Filed": item.filed.isoformat() if item.filed else "—",
    }
    st.dataframe(
        pd.DataFrame({"Field": list(facts), "Value": list(facts.values())}),
        hide_index=True,
        width="stretch",
    )
    if item.numbers:
        st.caption("Figures this item states, as stored")
        st.markdown(" · ".join(num(f"{value:,.4g}") for value in item.numbers))


def ratio_chart(series: RatioSeries, *, height: int = 150) -> None:
    """One ratio's point-in-time history.

    A zero line is drawn when the series crosses it, because a coverage ratio
    going negative is a different event from one merely falling and the axis
    should say so.
    """
    observed = series.observed
    if len(observed) < 2:
        st.caption("Not enough point-in-time history to plot.")
        return
    frame = pd.DataFrame(
        {"Period": [p.period for p in observed], "Value": [p.value for p in observed]}
    )
    base = alt.Chart(frame).encode(
        x=alt.X("Period:O", title=None, axis=alt.Axis(labelAngle=0, labelFontSize=10)),
        y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=False)),
        tooltip=["Period", alt.Tooltip("Value:Q", format=",.3f")],
    )
    layers = [base.mark_line(point=True, strokeWidth=2)]
    values = [p.value for p in observed if p.value is not None]
    if values and min(values) < 0 < max(values):
        layers.append(
            alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[3, 3]).encode(y="y:Q")
        )
    st.altair_chart(alt.layer(*layers).properties(height=height), width="stretch")


def scale_chart(points, *, currency: bool, height: int = 150) -> None:
    observed = [p for p in points if p.value is not None]
    if len(observed) < 2:
        st.caption("Not enough point-in-time history to plot.")
        return
    frame = pd.DataFrame(
        {"Period": [p.period for p in observed], "Value": [p.value for p in observed]}
    )
    chart = (
        alt.Chart(frame)
        .mark_area(line=True, opacity=0.25)
        .encode(
            x=alt.X("Period:O", title=None, axis=alt.Axis(labelAngle=0, labelFontSize=10)),
            y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=currency)),
            tooltip=["Period", alt.Tooltip("Value:Q", format=",.4g")],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def driver_chart(bars: Sequence[DriverBar], *, height: int = 240) -> None:
    """Attribution by dimension, as a diverging bar.

    Filing-artefact groups are drawn in a distinct colour and labelled, not
    filtered out: a model reacting to an absent tag is not a finding about
    leverage, and a chart that hid it would read as though every driver were
    financial.
    """
    if not bars:
        st.caption("No attribution recorded for this assessment.")
        return
    frame = pd.DataFrame(
        {
            "Group": [b.group.replace("_", " ") for b in bars],
            "Contribution": [b.contribution for b in bars],
            "Share": [b.share for b in bars],
            "Kind": [
                "About the filing, not the company" if b.is_filing_artefact else "Financial"
                for b in bars
            ],
        }
    )
    chart = (
        alt.Chart(frame)
        .mark_bar()
        .encode(
            x=alt.X("Contribution:Q", title="Contribution to the score (model's own units)"),
            y=alt.Y("Group:N", sort="-x", title=None),
            color=alt.Color(
                "Kind:N",
                legend=alt.Legend(orient="bottom", title=None),
                scale=alt.Scale(
                    domain=["Financial", "About the filing, not the company"],
                ),
            ),
            tooltip=[
                "Group",
                alt.Tooltip("Contribution:Q", format="+,.3f"),
                alt.Tooltip("Share:Q", format=".1%", title="Share of attribution"),
            ],
        )
        .properties(height=height)
    )
    st.altair_chart(chart, width="stretch")


def ratio_grid(series: Sequence[RatioSeries], *, columns: int = 3) -> None:
    """A category's ratios as a small-multiples grid."""
    plottable = [s for s in series if len(s.observed) >= 2]
    empty = [s for s in series if len(s.observed) < 2]
    for start in range(0, len(plottable), columns):
        row = st.columns(columns, gap="medium")
        for column, item in zip(row, plottable[start : start + columns], strict=False):
            with column:
                st.markdown(f"**{item.name}**")
                latest = item.latest
                change = item.change
                direction = ""
                if change is not None:
                    arrow = "trending_up" if change > 0 else "trending_down"
                    direction = f" :material/{arrow}: {num(f'{change:+,.2f}')}"
                st.markdown(f"{num(format_ratio(latest))}{direction}")
                st.caption(item.formula)
                ratio_chart(item, height=120)
    if empty:
        st.caption(
            "Not enough point-in-time history to plot: " + ", ".join(sorted(s.name for s in empty))
        )


def metric_strip(scale: dict, history: dict) -> None:
    """Size and cash generation, with history behind each figure."""
    from credit_risk_copilot.workspace import SCALE_FIELDS

    present = [(key, SCALE_FIELDS[key]) for key in SCALE_FIELDS if key in scale]
    if not present:
        st.caption("No point-in-time panel rows for this company.")
        return
    for start in range(0, len(present), 3):
        row = st.columns(3, gap="medium")
        for column, (key, (label, kind)) in zip(row, present[start : start + 3], strict=False):
            with column:
                point = scale[key]
                shown = (
                    format_currency(point.value)
                    if kind == "currency_from_log"
                    else format_percent(point.value)
                )
                st.caption(label)
                st.markdown(f"### {num(shown)}")
                st.caption(f"{point.period} · derived from the point-in-time panel")
                scale_chart(history.get(key, ()), currency=kind == "currency_from_log", height=90)


def company_row(card: CompanyCard, *, url: str) -> None:
    """One company as a dense row: identity, three reads, why it surfaced.

    "Open" is a link rather than a button. Navigation by link cannot
    half-succeed, survives a reload, and gives every workspace a URL worth
    bookmarking -- see `_nav.py` for why that replaced a programmatic page
    switch.
    """
    with st.container(border=True):
        left, mid, right = st.columns([3, 4, 2], gap="medium", vertical_alignment="center")
        with left:
            st.markdown(f"**{card.company}**")
            st.caption(
                f"CIK {card.cik} · as of {card.as_of.isoformat()}"
                + (f" · {card.period_label}" if card.period_label else "")
            )
        with mid:
            marks = []
            for read in card.reads:
                icon = CONCERN_ICONS[read.concern]
                colour = CONCERN_COLORS[read.concern]
                marks.append(f":{colour}-badge[{icon} {read.title}]")
            st.markdown(" ".join(marks))
            st.caption(" · ".join(r.headline for r in card.reads))
        with right:
            st.markdown(state_badge(card.state))
            st.link_button("Open", url, icon=":material/arrow_forward:", width="stretch")


def evidence_picker(items: Sequence[EvidenceItem], *, key: str) -> None:
    """A table of evidence with a detail panel for the selected row.

    Selection rather than expanders: an analyst comparing two items wants one
    detail panel that changes, not fifteen accordions to open and close.
    """
    frame = evidence_table(items)
    event = st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        height=340,
        on_select="rerun",
        selection_mode="single-row",
        key=key,
        column_config={
            "Statement": st.column_config.TextColumn(width="large"),
            "ID": st.column_config.TextColumn(width="small"),
        },
    )
    rows = event.selection.rows if event and event.selection else []
    if not rows:
        st.caption("Select a row to see the evidence behind it.")
        return
    with st.container(border=True):
        evidence_detail(items[rows[0]])
