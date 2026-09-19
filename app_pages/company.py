"""The company workspace: the centrepiece of the product.

The page answers the analyst's questions in the order they are actually
asked, top to bottom:

    What do the three methods say?      -> the three reads
    Where do they disagree?             -> disagreements, with both sides
    What are the numbers doing?         -> financials and ratio trends
    Why does the model rank it there?   -> attribution, with its caveats
    What did the filer actually say?    -> verbatim disclosures
    Where did any of this come from?    -> the evidence register
    What is my call?                    -> the review action

There is no risk score at the top, and that is the most deliberate decision
on the page. What sits there instead is three independent verdicts side by
side — because the analyst learns more from "the ratios are calm, the model
ranks this in the top 3%, and the filer states going-concern doubt" than from
any average of those three, and the disagreement between them is a finding
the average would destroy.
"""

from __future__ import annotations

import streamlit as st

from app_pages import _data, _ui
from credit_risk_copilot.review.models import (
    AnalystReview,
    CreditWatchStatus,
    ReviewDecision,
)
from credit_risk_copilot.workspace import (
    CONCERN_LABELS,
    format_percent,
)

if not _data.store_exists():
    st.error("No workspace database found.", icon=":material/database_off:")
    st.stop()

cik = _data.selected_cik()
if cik is None:
    st.title("Company", anchor=False)
    st.info("Pick a company from the sidebar, or open one from the desk.", icon=":material/search:")
    st.stop()

versions = _data.history(cik)
if not versions:
    st.error("No assessments recorded for this company.", icon=":material/error:")
    st.stop()

# --- header ---------------------------------------------------------------
chosen_id = st.session_state.get("assessment_id") or versions[0].assessment_id
entry = next((v for v in versions if v.assessment_id == chosen_id), versions[0])
ws = _data.workspace(entry.assessment_id, cik)
if ws is None:
    st.error("That assessment could not be loaded.", icon=":material/error:")
    st.stop()

card = ws.card
st.title(card.company, anchor=False)

identity, version, standing = st.columns([4, 3, 3], gap="medium", vertical_alignment="center")
with identity:
    st.caption(
        f"CIK {card.cik} · {card.n_evidence} evidence items · "
        f"{len(versions)} assessment version(s) on file"
    )
    st.markdown(_ui.attention_pills(card))
with version:
    # FR-05 is a product feature, not plumbing: the analyst can stand at any
    # past date and see only what was filed by then. The gate enforces it.
    labels = {
        v.assessment_id: f"{v.as_of} · {v.period_label or '—'}"
        + ("" if v.is_current else " (superseded)")
        for v in versions
    }
    picked = st.selectbox(
        "Assessment as of",
        [v.assessment_id for v in versions],
        index=[v.assessment_id for v in versions].index(entry.assessment_id),
        format_func=lambda aid: labels[aid],
        key="version_picker",
    )
    if picked != entry.assessment_id:
        st.session_state["assessment_id"] = picked
        st.rerun()
    st.caption("Only filings available on this date informed this assessment.")
with standing:
    st.markdown(_ui.state_badge(entry.state))
    st.markdown(_ui.watch_badge(entry.watch_status))

st.divider()

# --- the three reads ------------------------------------------------------
_ui.section(
    "What the three methods say",
    "Three independent readings of the same filing. Their failure modes are "
    "unrelated, so agreement means something and disagreement means something else.",
)
_ui.three_reads_row(card)

# --- disagreement / agreement --------------------------------------------
left, right = st.columns(2, gap="large")
with left:
    st.markdown("##### Where they disagree")
    if not ws.contradictions:
        st.markdown(":green-badge[:material/check: No contradictions detected]")
        st.caption("The layers produced no incompatible readings for this filing.")
    for finding in ws.contradictions:
        with st.container(border=True):
            st.markdown(
                f":orange-badge[:material/error: {finding.code.value.replace('_', ' ')}]"
                + (f" · {finding.dimension}" if finding.dimension else "")
            )
            st.markdown(finding.explanation)
            st.caption(f"**To check:** {finding.resolution_hint}")
            st.caption(
                f"{finding.left_layer.value.replace('_', ' ')} vs "
                f"{finding.right_layer.value.replace('_', ' ')} · "
                f"{len(finding.cited)} cited item(s)"
            )
with right:
    st.markdown("##### Where they agree")
    if not ws.corroborations:
        st.caption("No independent agreement recorded for this filing.")
    for finding in ws.corroborations:
        with st.container(border=True):
            st.markdown(
                f":green-badge[:material/join_inner: {finding.code.value.replace('_', ' ')}]"
                + (f" · {finding.dimension}" if finding.dimension else "")
            )
            st.markdown(finding.explanation)
            st.caption(
                f"{len(finding.layers)} independent layer(s) · "
                f"{len(finding.supporting)} cited item(s)"
            )

st.divider()

# --- deep sections --------------------------------------------------------
financials, model, language, evidence, review = st.tabs(
    [
        "Financials & ratios",
        "Model attribution",
        "Filing language",
        "Evidence register",
        "Draft & review",
    ]
)

with financials:
    _ui.section(
        "Scale and cash generation",
        "Point-in-time values: each figure was computable from filings available "
        "at that period, not restated afterwards.",
    )
    _ui.metric_strip(ws.scale, ws.scale_history)
    st.caption(
        "Revenue and total assets are recovered exactly from the panel's stored "
        "natural logs of the reported figures. EBITDA is not shown because the "
        "canonical schema does not define it — see Method & limits."
    )
    st.divider()
    _ui.section("Ratio trends", "The 13-ratio catalog, grouped as the health layer groups it.")
    categories = [
        ("liquidity", "Liquidity"),
        ("leverage", "Leverage"),
        ("profitability", "Profitability"),
        ("coverage", "Coverage"),
        ("cash_flow", "Cash flow"),
    ]
    available = [(key, label) for key, label in categories if ws.ratios_in(key)]
    for tab, (key, _label) in zip(
        st.tabs([label for _, label in available]), available, strict=False
    ):
        with tab:
            _ui.ratio_grid(ws.ratios_in(key))

with model:
    if ws.score_percentile is None:
        st.info("The model did not score this filing.", icon=":material/block:")
    else:
        head, note = st.columns([1, 2], gap="large")
        with head, st.container(border=True):
            st.caption("Position in the monitored ranking")
            st.markdown(f"# {_ui.num(f'{ws.score_percentile:.1f}')}")
            st.caption(
                f"percentile among companies scored in the same year · {ws.model_name or 'model'}"
            )
        with note:
            st.warning(
                "**This is a ranking position, not a probability.** The model is not "
                "calibrated, and its training base rate is a property of the sampling "
                "design rather than of any real portfolio. Read it as "
                '*"unusually high in this year\'s monitored population"* — never as '
                '*"n% chance of default"*.',
                icon=":material/warning:",
            )
    st.divider()
    _ui.section(
        "What moved the score",
        "Attribution by financial dimension. Contributions are on the model's own "
        "additive scale; the share of total attribution is the number worth reading.",
    )
    _ui.driver_chart(ws.drivers)
    artefacts = [d for d in ws.drivers if d.is_filing_artefact]
    if artefacts:
        share = sum(d.share for d in artefacts)
        st.caption(
            f"{format_percent(share)} of this prediction's attribution is about the "
            "filing's completeness rather than the company's finances."
        )
    if ws.caveats:
        st.markdown("##### Caveats attached to this prediction")
        st.caption(
            "Structured, not prose: each is a specific, checkable reason the output "
            "must not be read at face value. They travel with the number."
        )
        for code, message in ws.caveats:
            with st.container(border=True):
                st.markdown(f":orange-badge[:material/info: {code.replace('_', ' ')}]")
                st.caption(message)

with language:
    _ui.section(
        "What the filer states about itself",
        "Disclosure statements, gated on grammatical mood. Every 10-K discusses "
        "default in the conditional; only an asserted statement is evidence.",
    )
    if ws.coverage_gaps:
        st.warning(
            "**Some sections were not located in this filing**, so an absence of "
            "signals here is partly an absence of reading: "
            + ", ".join(gap.section for gap in ws.coverage_gaps),
            icon=":material/visibility_off:",
        )
    if not ws.narrative:
        st.caption("No disclosure signals emitted for this filing.")
    for item in ws.narrative:
        with st.container(border=True):
            mood = (
                ":orange-badge[:material/campaign: Stated]"
                if item.is_asserted
                else ":blue-badge[:material/block: Explicitly denied]"
                if item.assertion == "negated"
                else f":gray-badge[{item.assertion}]"
            )
            st.markdown(f"**{item.label}** {mood} :gray-badge[specificity {item.specificity}]")
            if item.quote:
                st.markdown(f"> {item.quote}")
            st.caption(
                f"{item.occurrences} occurrence(s) · {item.section or 'unknown section'}"
                + (f" · {item.accession}" if item.accession else "")
                + f" · {item.evidence_id}"
            )

with evidence:
    _ui.section(
        "Every fact this assessment rests on",
        "The register Phase 12's synthesis cites and Phase 13 stores. Each item is "
        "content-addressed, so a stored citation cannot silently repoint.",
    )
    layers = st.multiselect(
        "Layer",
        sorted({item.layer.value for item in ws.evidence}),
        default=None,
        placeholder="All layers",
        key="evidence_layers",
    )
    concerns = st.segmented_control(
        "Read",
        ["Elevated", "Nothing flagged", "No read"],
        selection_mode="multi",
        key="evidence_concerns",
    )
    items = list(ws.evidence)
    if layers:
        items = [i for i in items if i.layer.value in layers]
    if concerns:
        items = [i for i in items if CONCERN_LABELS[i.concern] in concerns]
    st.caption(f"{len(items)} of {len(ws.evidence)} items")
    _ui.evidence_picker(items, key="evidence_table")

with review:
    _ui.section(
        "Draft and analyst decision",
        "The AI draft is immutable and stored with its grounding verdict. Your "
        "decision is a separate record and can never be edited — corrections are "
        "new records.",
    )
    if entry.draft_id:
        st.markdown(
            _ui.state_badge(entry.state)
            + (
                " :green-badge[:material/verified: Draft passed grounding checks]"
                if entry.draft_accepted
                else " :red-badge[:material/gpp_bad: Draft failed grounding checks]"
            )
        )
    else:
        st.info(
            "No AI draft has been generated for this assessment. The synthesis layer "
            "needs a configured LLM provider (`ANTHROPIC_API_KEY` or `GEMINI_API_KEY`); "
            "every deterministic section above works without one.",
            icon=":material/draw:",
        )

    st.markdown("##### Record your decision")
    st.caption(
        "Nothing is pre-selected. Rejecting is as easy as approving, and both are permanent."
    )
    with st.form("review_form", border=True):
        decision = st.radio(
            "Decision",
            list(ReviewDecision),
            index=None,
            format_func=lambda d: {
                ReviewDecision.APPROVE: "Approve — an accurate basis for my assessment",
                ReviewDecision.MODIFY: "Modify — partly right, my correction below",
                ReviewDecision.REJECT: "Reject — wrong or unusable",
            }[d],
            key="review_decision",
        )
        watch = st.radio(
            "Credit watch status",
            list(CreditWatchStatus),
            index=None,
            format_func=lambda s: {
                CreditWatchStatus.STABLE: "Stable — no action beyond the normal cycle",
                CreditWatchStatus.MONITOR: "Monitor — look again next filing",
                CreditWatchStatus.WATCHLIST: "Watchlist — review out of cycle",
                CreditWatchStatus.ESCALATE: "Escalate — to a risk or portfolio manager",
            }[s],
            key="review_watch",
        )
        analyst = st.text_input("Analyst", value=st.session_state.get("analyst", ""), key="analyst")
        comment = st.text_area(
            "Comment", placeholder="Required to modify or reject.", key="review_comment"
        )
        modified = st.text_area(
            "Your assessment (required to modify)",
            placeholder="Stored alongside the draft, never merged into it.",
            key="review_modified",
        )
        submitted = st.form_submit_button("Record decision", icon=":material/gavel:")

    if submitted:
        if decision is None or watch is None or not analyst.strip():
            st.error(
                "A decision, a credit watch status and your name are all required.",
                icon=":material/error:",
            )
        elif not entry.draft_id:
            st.error(
                "A review must reference the exact draft it reviewed, and no draft "
                "exists for this assessment yet.",
                icon=":material/error:",
            )
        else:
            try:
                _data.record_review(
                    AnalystReview(
                        review_id=f"RV-{entry.assessment_id}-{len(entry.reviews) + 1}",
                        draft_id=entry.draft_id,
                        assessment_id=entry.assessment_id,
                        analyst=analyst.strip(),
                        decision=decision,
                        watch_status=watch,
                        comment=comment.strip() or None,
                        modified_text=modified.strip() or None,
                    )
                )
            except ValueError as error:
                # The schema enforces FR-18; the UI surfaces the reason rather
                # than pre-validating it in a second place that could drift.
                st.error(str(error), icon=":material/rule:")
            else:
                st.success("Decision recorded.", icon=":material/check_circle:")
                st.rerun()

    if entry.reviews:
        st.markdown("##### Decisions on file")
        corrected = {r.supersedes_review_id for r in entry.reviews if r.supersedes_review_id}
        for record in entry.reviews:
            standing = record.review_id not in corrected
            with st.container(border=True):
                st.markdown(
                    f"**{record.decision.value.capitalize()}** by {record.analyst} · "
                    + _ui.watch_badge(record.watch_status)
                    + ("" if standing else " :gray-badge[superseded by a correction]")
                )
                if record.comment:
                    st.caption(record.comment)
                if record.modified_text:
                    st.markdown(f"> {record.modified_text}")
                st.caption(record.recorded_at.strftime("%Y-%m-%d %H:%M UTC"))
