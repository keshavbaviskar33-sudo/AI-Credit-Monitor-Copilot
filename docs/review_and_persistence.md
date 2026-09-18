# Analyst Review & Append-Only Persistence — Phase 13

| | |
|---|---|
| **Status** | Complete — verified on the full 202-assessment corpus |
| **Date** | 2026-09-19 |
| **Decisions** | [D-046](decision_log.md) append-only in SQL, not by convention · [D-047](decision_log.md) supersession is derived · [D-048](decision_log.md) stdlib `sqlite3`, rules in the type · [D-049](decision_log.md) the watch vocabulary is about action |
| **Code** | `src/credit_risk_copilot/review/` |
| **Scripts** | `phase13_audit.py` |
| **Requirements** | FR-18 (approve/modify/reject) · FR-19 (immutable draft, separate edits) · FR-20 (watch status only by analyst) · FR-21 (versions recorded) · FR-22 (new version, old ones accessible) |
| **Related** | [user_workflow.md](user_workflow.md) §6–7 · [grounded_synthesis.md](grounded_synthesis.md) (what gets stored) · [combined_assessment.md](combined_assessment.md) |

> **This is where [D-003](decision_log.md) stops being a principle.** "The
> analyst owns every final judgement" has been the project's first sentence
> since Phase 1 and, until this package, was enforced by nothing. A pipeline
> that drafts and a human who agrees are not a human-in-the-loop system unless
> disagreeing is as easy, as recorded and as permanent as agreeing.
>
> Phase 15 was merged into this one ([D-045](decision_log.md)): persisting
> immutable drafts with versioning and history queries *is* the database
> architecture, and scheduling a second phase to design it afterwards invites
> rewriting a working schema to justify the phase.

---

## 1. Three guarantees, each enforced rather than intended

| Guarantee | How | Not by |
|---|---|---|
| History is append-only | `BEFORE UPDATE` / `BEFORE DELETE` triggers `RAISE(ABORT)` on every table | a convention in a module nobody reads |
| The draft is immutable and verifiable | stored with its Phase 12 verdict and a content hash checked on every read | trusting that nothing wrote to it |
| Judgement is the analyst's | `AnalystReview` cannot be constructed without a decision and a watch status, neither defaulted | a service-layer check one code path can skip |

The first is the one that matters most. A store that is append-only *by
convention* is append-only until the first hurried afternoon. A store whose
`UPDATE` raises is append-only in a way an auditor can verify without reading
any Python — and the test suite attacks the raw connection directly, because a
rule that can only be exercised through the module that provides it has not
been tested.

## 2. What is stored, and what is derived

```text
assessment ──1:N── draft ──1:N── review
    │                               │
    │                               └── supersedes_review_id ──┐
    └── (supersession: derived from as_of ordering)            │
                                    └──────────────────────────┘
                                       a correction points at
                                       what it corrects; neither
                                       row is ever edited
```

**Stored:** the things somebody or something *did* — an assessment was
produced, a draft was generated, an analyst decided.

**Derived:** supersession and lifecycle state. `user_workflow.md` §6 lists
five states, and four of them are the result of an action someone took.
`SUPERSEDED` is the result of an action taken about a *different* assessment —
a newer filing arriving — so recording it would mean going back and updating a
row that was already written, which is the one operation this package refuses.
So the latest assessment for a company is current, every earlier one is
superseded, and both are computed at read time ([D-047](decision_log.md)).

A superseded assessment **keeps its review**. It is not an unreviewed
assessment; it is a reviewed one that is no longer the latest.

## 3. Corrections are records, not edits

An analyst who changes their mind writes a new review pointing at the one it
corrects. Both survive in `history()`; only one is `effective_review`. This is
`user_workflow.md`'s "corrections are new review records", and it is why there
is no `update` method anywhere in the package.

The same shape gives FR-20 its teeth: `watch_status` lives on the review, not
on the assessment, so nothing in the pipeline can write it. An unreviewed
company's status is `None` — **not** `STABLE`, because defaulting it would
manufacture a judgement nobody made.

## 4. FR-18 lives in the type

A `modify` or `reject` without a comment raises at construction, not at save.
A validation in the storage layer protects the database; a validation in the
type protects every code path that will ever build one — including the Phase 14
UI and whatever comes after.

Three rules, and the reasoning for each:

- **Modify and reject require a comment.** FR-18.
- **Approve does not.** Demanding a justification for agreement is how you
  train people to write "ok", and a field full of "ok" is worse than an empty
  one.
- **`decision` and `watch_status` have no defaults.** `user_workflow.md` §7
  asks for "no default review action" as an anti-automation-bias measure, and
  a schema defaulting to `APPROVE` would hand the UI a pre-selected answer
  whatever the UI intended.

Plus one the requirements do not name: an `approve` carrying `modified_text` is
refused. An ambiguous record surfaces months later in an audit rather than now.

## 5. The credit watch vocabulary, confirmed

`user_workflow.md` §5 proposed `stable · monitor · watchlist · escalate` and
left it "to be confirmed in Phase 13". **Confirmed as proposed**
([D-049](decision_log.md)), because the four terms describe *what the analyst
will do next* rather than how bad they think the company is.

A severity vocabulary (`low`/`medium`/`high`) would be a composite risk score
wearing words — the thing [D-010](decision_log.md),
[D-022](decision_log.md), [D-033](decision_log.md) and
[D-036](decision_log.md) have each refused — and it would invite comparison
with the model's ranking, which is a different quantity measured a different
way.

## 6. Verified on the whole corpus

Unit tests prove the rules on a handful of rows. `phase13_audit.py` records
every assessment the pipeline has produced, closes the database, reopens it and
checks.

| | |
|---|---|
| Assessments / drafts / reviews recorded | **202 / 202 / 68** |
| Companies | 163, of which **36 have several assessments** |
| Round-trip mismatches after close-and-reopen | **0** |
| Edit operations attempted on the full database | 6 (`UPDATE` + `DELETE` × 3 tables) |
| Edit operations refused | **6 of 6** |

Derived state across 202 assessments: 109 `draft`, 19 `approved`, 19
`modified`, 16 `rejected`, **39 `superseded`** — of which **14 retain a
review**, which is the half of FR-22 that is easiest to lose silently.

Performance, against the "interactive at demo scale" NFR:

| Operation | Time | Scale |
|---|---|---|
| Record everything | 3.14 s | 472 rows |
| Read back and verify all assessments | 0.17 s | 202 |
| `watchlist()` | 0.025 s | 163 companies |
| `history()` for every company | 0.033 s | 163 queries |

Database size: **4.46 MB** for 202 assessments with full evidence payloads —
about 22 KB each, which is what storing the complete evidence register rather
than a summary costs. It is the right trade: Phase 12's citations resolve
against the stored assessment, so a summary would break the audit chain to save
megabytes.

## 7. Limitations

1. **`analyst` is free text.** The MVP has no authentication. A real
   deployment binds this to an authenticated principal; the column exists so
   that change is a substitution rather than a migration.
2. **The triggers protect rows, not the schema.** Someone with file access can
   `DROP TRIGGER` and then edit — the round-trip test does exactly that to
   verify the hash check still catches tampering. The guarantee is against
   accident and convention-drift, not against an administrator with the file
   and a motive. Content hashes are the second line: a tampered payload fails
   on read.
3. **No migration path.** `SCHEMA_VERSION` is checked on open and a mismatch
   raises rather than migrating. An append-only audit store that silently
   rewrites itself to a new shape is a contradiction; converting means
   exporting and re-recording, deliberately.
4. **Concurrency is untested.** One process, one connection. SQLite would
   handle a second reader; nothing here has been exercised under concurrent
   writers, and the NFR does not ask for it yet.
5. **The corpus harness reviews are synthetic.** The 68 reviews in §6 were
   generated to exercise every decision path at scale. They demonstrate the
   store; they are not analyst judgements and are not in any reported result.

## 8. What Phase 14 receives

```python
store.watchlist()          # each company's current assessment, A-Z
store.history(cik)         # every version, newest first, reviews intact
store.load_assessment(id)  # hash-verified, for evidence drill-down
store.load_draft(id)       # the draft *and* its grounding verdict
store.record_review(...)   # the only way a judgement enters the system
```

Three things the UI must not do, all of which the layer below now makes
awkward rather than merely discouraged:

- **Do not pre-select a review action.** There is no default in the schema; do
  not add one in the form.
- **Do not show a draft without its verdict.** `draft_accepted` is on
  `AssessmentHistory` for this reason; a rejected draft rendered as prose is
  the failure Phase 12 exists to prevent.
- **Do not sort the watchlist by anything resembling risk.** It is returned
  alphabetically. There is no risk ordering in this project to sort by, and
  inventing one in a UI would be the composite score arriving at last,
  disguised as a sort key.
