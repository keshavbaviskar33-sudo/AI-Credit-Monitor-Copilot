"""Method and limits: what this system produces, and what it refuses to.

Most analytics products bury this page. Here it is navigation-level, because
the product's central claim is that every number on screen traces to a filing
— and a claim like that is only worth anything if the exceptions are listed
where an analyst will actually find them.

The table of things *not* shown is the most important content in the app.
Several of them are figures a credit interface would normally display, and a
reader who does not find them deserves to know whether they are missing
because the data is absent or because showing them would be a lie.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app_pages import _data

st.title("Method & limits", anchor=False)
st.caption(
    "What is measured, what is derived, and what this product deliberately does not produce."
)

st.subheader("The three readings", anchor=False)
st.markdown(
    """
Every assessment is read three ways, by methods whose failure modes are
unrelated. That independence is the point: a mis-mapped accounting tag does
not make a filer write "substantial doubt", and a false-positive text pattern
does not move a current ratio.

| Reading | Method | What it can say |
|---|---|---|
| **Financial trends** | Deterministic ratios over a point-in-time window | A dimension is deteriorating, improving, stable, or has too little history |
| **Model ranking** | Gradient-boosted 365-day hazard model, walk-forward | Where this filing sits in the ranking **of its own scoring year** |
| **Filing language** | Disclosure patterns gated on grammatical mood | What the filer **states** about itself, with the sentence attached |
"""
)

st.divider()
st.subheader("What this product does not produce", anchor=False)
st.markdown(
    "Each of these is absent by decision, not by omission. Where a number is "
    "missing, the reason is in the last column."
)

st.dataframe(
    pd.DataFrame(
        [
            {
                "Not shown": "Overall risk score (e.g. 72 / 100)",
                "Why": (
                    "There is no combined score to show. Collapsing a ranking metric, a "
                    "threshold-driven trend label and a text match into one digit would "
                    "destroy the disagreements between them — which is the only finding "
                    "no single layer produces."
                ),
            },
            {
                "Not shown": "Probability of default",
                "Why": (
                    "The model is not calibrated (slope 0.81) and its training base rate "
                    "is a property of the sampling design, not of any portfolio. The "
                    "output is a ranking position and is labelled as one everywhere."
                ),
            },
            {
                "Not shown": "Confidence percentage",
                "Why": (
                    "No confidence number is produced anywhere in the pipeline. In place "
                    "of a trust meter, each prediction carries structured caveats and "
                    "every claim carries its evidence — which research on provenance "
                    "interfaces finds more effective than a single score."
                ),
            },
            {
                "Not shown": "Peer or sector benchmarks",
                "Why": (
                    "No industry classification or comparable set exists in the pipeline. "
                    "The Compare page shows companies you cover, and says so."
                ),
            },
            {
                "Not shown": "EBITDA, Debt/EBITDA, Net debt",
                "Why": (
                    "EBITDA is not one of the 26 canonical concepts, so any EBITDA figure "
                    "would be an assumption about depreciation and amortisation rather "
                    "than a reported value. EBIT and interest coverage are shown instead."
                ),
            },
            {
                "Not shown": "Quarterly periods",
                "Why": "The pipeline covers annual filings (10-K) only.",
            },
            {
                "Not shown": "Earnings-call sentiment",
                "Why": (
                    "The text layer does not score sentiment and reads no earnings calls. "
                    "It extracts specific disclosure statements from the filing and "
                    "classifies their grammatical mood — an assertion is evidence, a "
                    "conditional is not."
                ),
            },
            {
                "Not shown": "Efficiency ratios (DSO, DIO, asset turnover)",
                "Why": "Not in the 13-ratio catalog, so no measured values exist.",
            },
        ]
    ),
    hide_index=True,
    width="stretch",
    column_config={
        "Not shown": st.column_config.TextColumn(width="medium"),
        "Why": st.column_config.TextColumn(width="large"),
    },
)

st.divider()
st.subheader("Where the numbers come from", anchor=False)
st.markdown(
    """
| On screen | Source | Status |
|---|---|---|
| Ratios, trends, dimension status | Canonical facts from as-filed XBRL, through the ratio catalog | **Measured** |
| Model percentile and attribution | Walk-forward out-of-time scoring; TreeSHAP from the fold's own estimator | **Measured** |
| Verbatim disclosure quotes | The filing text, with character spans; every quote is checked against its source | **Measured** |
| Revenue, total assets | Recovered by exponentiating the panel's stored natural log of the reported figure | **Derived, exactly invertible** |
| Contradictions and agreements | Explicit rules over the evidence register | **Derived by rule** |
| Analyst decisions and watch status | Recorded by a person, append-only | **Human judgement** |

Nothing on any screen is simulated, imputed or filled in. A ratio that could
not be computed from the filings available at the as-of date renders blank —
never zero.
"""
)

st.divider()
st.subheader("Known limitations of the analysis", anchor=False)
st.markdown(
    """
These are measured, not suspected:

- **The comparison cohort is confounded.** The same features predict the
  sampling design at least as well as they predict bankruptcy. Pooled model
  metrics are not quotable as credit discrimination; the ranking is still
  usable as a *ranking*.
- **About 44% of one model's attribution tracked data availability**, not the
  company. The shipped model largely removed this, and attribution that is
  about the filing rather than the company is drawn separately in the
  attribution chart.
- **Roughly one filing in five yields no MD&A section.** Where a section was
  not located, the company page says so rather than reporting "no signals".
- **The narrative layer's precision is 73% overall**, and 13/13 on the three
  highest-lift disclosure codes. Recall is built but unlabelled and is not
  reported.
- **Combining the layers does not improve ranking accuracy.** At a matched
  alert budget, three-layer agreement was exactly as precise as the model
  alone. The layers are shown together for their *disagreements* and their
  citations, not for a lift that was measured and not found.
"""
)

st.divider()
st.subheader("Human-in-the-loop", anchor=False)
st.markdown(
    """
The system drafts. The analyst decides.

- The AI draft is **immutable** and stored with its grounding verdict — whether
  code could verify every citation, number and quotation in it.
- A draft that fails those checks is shown **with the failure**, never quietly
  regenerated.
- Analyst decisions are stored **separately** from the draft and can never be
  edited or deleted. A correction is a new record that points at the one it
  corrects.
- The credit watch status can only be set by an analyst action. A company
  nobody has reviewed has **no status** — not a default one.
"""
)

if _data.store_exists():
    st.divider()
    cards = _data.cards()
    panel = _data.panel()
    st.caption(
        f"This workspace is reading {len(cards)} companies from the audit store, "
        f"with {len(panel):,} point-in-time panel rows behind the trend charts."
    )
