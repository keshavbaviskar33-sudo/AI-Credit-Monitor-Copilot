"""Credit analyst workspace — application entry point.

A decision-support workspace, not an underwriting system. Every screen is
built so the analyst moves along one path:

    what happened  ->  why  ->  does it matter  ->  what do I check  ->  my call

Run it with:

    uv run streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Credit analyst workspace",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="expanded",
)

from app_pages import _data  # noqa: E402

for key, default in (("cik", None), ("assessment_id", None)):
    if key not in st.session_state:
        st.session_state[key] = default

# Page objects are built fresh on every script run. Streamlit lets a Page be
# run once, so holding them at module level in a helper -- where Python's
# import cache keeps them alive across runs -- raises "this page cannot be
# called directly" on the second interaction.
#
# Navigation between pages is done with ordinary links to these `url_path`s
# rather than with `st.switch_page`, which was tried first and proved
# unreliable here: accepted without error and then silently doing nothing.
# A link cannot half-work, survives a reload, and makes every company
# workspace a URL an analyst can bookmark or paste to a colleague.
navigation = st.navigation(
    [
        st.Page(
            "app_pages/desk.py",
            title="Desk",
            icon=":material/inbox:",
            url_path="desk",
            default=True,
        ),
        st.Page(
            "app_pages/company.py",
            title="Company",
            icon=":material/domain:",
            url_path="company",
        ),
        st.Page(
            "app_pages/compare.py",
            title="Compare",
            icon=":material/compare_arrows:",
            url_path="compare",
        ),
        st.Page(
            "app_pages/audit.py",
            title="Audit trail",
            icon=":material/history:",
            url_path="audit",
        ),
        st.Page(
            "app_pages/method.py",
            title="Method & limits",
            icon=":material/help_center:",
            url_path="method",
        ),
    ]
)

with st.sidebar:
    st.markdown("### Credit analyst workspace")
    st.caption("Decision support. The analyst decides.")
    if _data.store_exists():
        index = _data.company_index()
        options = sorted(index, key=lambda cik: index[cik])
        current = _data.selected_cik()
        picked = st.selectbox(
            "Company",
            options,
            index=options.index(current) if current in options else None,
            format_func=lambda cik: index[cik],
            placeholder="Search coverage…",
            key="sidebar_company",
        )
        # A link rather than an automatic jump: the analyst stays where they
        # are until they ask to move, and the target is a real URL.
        st.link_button(
            "Open workspace",
            _data.company_url(picked if picked is not None else (current or 0)),
            icon=":material/arrow_forward:",
            width="stretch",
            disabled=picked is None and current is None,
        )
        st.caption(f"{len(options)} companies under coverage")
    st.divider()
    st.caption(
        "No combined risk score is shown anywhere in this product. "
        "See **Method & limits** for what the system does and does not produce."
    )

navigation.run()
