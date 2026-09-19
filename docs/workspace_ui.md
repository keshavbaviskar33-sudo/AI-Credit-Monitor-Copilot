# The Analyst Workspace — Phase 14

| | |
|---|---|
| **Status** | Complete — running against the real 202-assessment corpus |
| **Date** | 2026-09-19 |
| **Decisions** | [D-050](decision_log.md) three reads, not a score · [D-051](decision_log.md) the desk groups by reason · [D-052](decision_log.md) theme config over CSS, links over page switching |
| **Code** | `app.py` · `app_pages/` · `src/credit_risk_copilot/workspace/` |
| **Scripts** | `build_workspace_db.py` |
| **Requirements** | FR-01, FR-05 (replay), FR-10, FR-11, FR-18–FR-22 · NFR traceability, fail-safe, accessibility |
| **Related** | [user_workflow.md](user_workflow.md) · [review_and_persistence.md](review_and_persistence.md) · [combined_assessment.md](combined_assessment.md) |

> **The centre of the screen is where a risk score would normally go, and it
> is occupied by three independent verdicts instead.** That is the whole
> design. An analyst learns more from *"the ratios are calm, the model ranks
> this in the top 3%, and the filer states going-concern doubt"* than from any
> average of those three — and the disagreement between them is a finding the
> average would destroy.

---

## 1. What the product asked for, and what the system can honestly show

A credit interface conventionally opens with `RISK 72/100 · 84% confidence`.
This backend produces neither number, and four decisions explain why. So the
design started by mapping every conventional element onto what exists.

| Conventional element | What this workspace shows instead | Why |
|---|---|---|
| Risk score 0–100 | **Three layer reads** side by side | No combined score exists ([D-036](decision_log.md)) |
| Probability of default | **Percentile within the scoring year**, labelled as a ranking | Model is uncalibrated ([D-033](decision_log.md)) |
| Confidence % | **Structured caveats** attached to the number, and the evidence behind every claim | No confidence value is produced; research on provenance UI finds evidence beats trust meters |
| Peer benchmarks | **Companies you cover**, explicitly not a peer group | No sector classification in the pipeline |
| EBITDA, Debt/EBITDA | **EBIT and interest coverage** | EBITDA is not a canonical concept |
| Earnings-call sentiment | **Verbatim disclosure statements** with grammatical mood | The text layer is not a sentiment model ([D-035](decision_log.md)) |

Every one of those substitutions is stated to the analyst on the
**Method & limits** page, which is navigation-level rather than buried. The
table of things *not* shown is the most important content in the app: a claim
that every number traces to a filing is only worth something if the exceptions
are listed where someone will find them.

## 2. Information architecture

Five destinations, following the analyst's actual question sequence rather
than the system's module structure.

```text
Desk         what needs me today, and why      (grouped by reason, never ranked)
Company      the workspace                     (the centrepiece)
Compare      companies I cover, side by side   (explicitly not peers)
Audit trail  what did we know, and who decided (append-only history)
Method       what this system will not tell me (the honest page)
```

The company page answers questions top to bottom in the order they are asked:

```text
What do the three methods say?     -> the three reads
Where do they disagree?            -> both sides, each cited, neither adjudicated
What are the numbers doing?        -> point-in-time ratio trends
Why does the model rank it there?  -> attribution, with caveats attached
What did the filer actually say?   -> verbatim quotes, with mood
Where did any of this come from?   -> the evidence register
What is my call?                   -> the review action
```

## 3. The three reads

Each panel states **its own method**, because an analyst comparing three
verdicts needs to know that one is arithmetic over XBRL facts, one is a fitted
model, and one is a pattern match over English. Their failure modes are
unrelated, which is precisely why agreement is informative and disagreement is
a finding.

A layer that did not run shows *"Did not run"* with the reason — never a calm
verdict. `LayerRead.available` is kept apart from `concern=QUIET` in the type,
because "we looked and found nothing" and "we did not look" are different
answers and conflating them is the failure the whole pipeline is shaped to
prevent.

Below the reads sit **Where they disagree** and **Where they agree**, each
finding naming both sides, the layers involved, how many items it cites, and —
for a contradiction — what to check. No rule adjudicates.

## 4. Two product features that fall out of the backend

**Historical replay is a control, not plumbing.** The company header carries an
*"Assessment as of"* selector listing every version on file. Picking an earlier
one shows the company as it was understood then, with the point-in-time gate
enforcing that no later filing leaked in. Most credit tools cannot do this at
all; here it was already guaranteed by `AsOfGate`, so the UI just exposes it.

**Every workspace is a URL.** `/company?cik=1503518` is bookmarkable and
pasteable. That came out of a bug — see [D-052](decision_log.md) — and is
better than the callback navigation it replaced.

## 5. Design language

| Decision | Reasoning |
|---|---|
| Warm neutral near-black (dark) and warm paper (light) | An analyst reads this for hours; a warm ground is calmer than blue-slate and stops the product reading as a generic template |
| Brass accent, single | Restraint. The accent marks attention, nothing else |
| **Numbers in JetBrains Mono** | The highest-value typographic choice in a financial UI: columns of ratios line up digit for digit. Done through the theme's code font, so it needs no CSS |
| 4px radii, borders not shadows | "Avoid excessive rounded rectangles" — 4px reads as an instrument, 12px as a consumer app |
| Amber = elevated, teal = quiet, grey = unknown | Deliberately **not** red/green. Risk is carried by icon + word + position, with colour as reinforcement only |
| Red reserved for *failures* | A rejected draft or a grounding violation — never for a company doing badly |
| Restrained heading scale (24px max) | A dense analytical page needs hierarchy, not billboard type |

Both light and dark are fully specified, so the theme switcher in Streamlit's
menu works. Almost none of this is CSS: it is `.streamlit/config.toml`, which
means it survives upgrades and applies to every widget, chart and table
consistently ([D-052](decision_log.md)).

## 6. Where the data comes from

| Section | Source | Status |
|---|---|---|
| Reads, contradictions, evidence, quotes, attribution, caveats | The Phase 13 append-only audit store | **Measured** |
| Ratio trends, scale history | The Phase 8 point-in-time panel — each row computable from filings available at that date | **Measured, point-in-time** |
| Revenue, total assets | `exp()` of the panel's stored natural log of the reported figure | **Derived, exactly invertible** |
| Reviews and watch status | Recorded by the analyst, append-only | **Human judgement** |

The demo store is built by `scripts/build_workspace_db.py`: **202 assessments
over 163 companies**, with no drafts and no reviews. That is deliberate — every
draft and decision the workspace shows should be one the person at the keyboard
actually made, and a store pre-seeded with synthetic reviews would put words in
an analyst's mouth on the first screen.

Nothing anywhere is simulated or imputed. A ratio that was not computable
renders blank, never zero.

## 7. Anti-automation-bias measures, enforced rather than styled

`user_workflow.md` §7 lists five. Four are now properties of the code:

1. **No default review action.** `AnalystReview` has no default decision and no
   default watch status, so the schema cannot hand the form a pre-selected
   answer.
2. **Contradictions sit above the review control**, not below it.
3. **Reject is as easy as approve** — same shape, same prominence, and
   `modify`/`reject` require a comment while `approve` does not.
4. **The draft carries its grounding verdict.** A draft that failed the Phase 12
   checks is shown *with the failure*.
5. **Absences are rendered.** Unlocated filing sections appear where signals
   would be.

## 8. Verification

- **754 tests pass** at the close of this phase (**758** as of Phase 19). 18 of
  them cover the workspace view models directly,
  including one that asserts no field named `score`, `confidence`, `rating` or
  `severity` exists on the objects the page renders — the combined score
  cannot reappear as a widget without failing a test.
- **Every page renders headlessly** under `streamlit.testing.v1.AppTest`
  against the real store.
- **Verified in a browser** at 1680×1050: desk, company header, three reads,
  disagreements and agreements, and the ratio-trend charts.

Two real defects were found by this work and fixed:

- **A missing point-in-time panel crashed the workspace** rather than degrading
  to "no trend charts", which its own docstring promised. Found by a test that
  passes an empty frame.
- **Caches were unbounded.** The per-company workspace cache grew by one full
  evidence register per company opened. Now bounded.

## 9. Limitations

1. **No AI draft is generated in-app.** The Draft & review tab shows a stored
   draft when one exists and otherwise says the synthesis layer needs a
   configured provider. Generating on demand is a small addition; the review
   workflow around it is complete.
2. **The review form requires a draft to exist**, because FR-19 binds a review
   to the exact draft it reviewed. Reviewing an assessment with no draft is
   currently refused rather than silently allowed.
3. **Not tested below tablet width.** Desktop and laptop are verified; the
   layout uses responsive containers but narrow phone widths are unexercised.
4. **`analyst` is free text** — there is no authentication in the MVP.
5. **Comparison is limited to eight companies** and aligns periods by fiscal
   label, not by calendar date.
6. **Streamlit does not hot-reload imported modules.** Editing anything under
   `app_pages/_*.py` or `workspace/` needs a server restart — this cost real
   debugging time and is recorded here so it costs nobody else any.
