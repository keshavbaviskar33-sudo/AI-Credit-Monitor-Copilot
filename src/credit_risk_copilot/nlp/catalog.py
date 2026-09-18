"""The risk-signal catalog: what to look for, and what it means.

Every pattern here is a reviewable claim about credit analysis, in the same way
that `concept_map.py`'s tag policies are reviewable claims about accounting and
`thresholds.py`'s constants are reviewable claims about ratio movement. A false
positive traces to one `pattern_id` and is fixed by editing one line, which is
the property that makes a rules layer defensible where a classifier would not
be (A-15).

## What is in the catalog and what is deliberately not

In: conditions a credit analyst would act on, that a filer is *required* to
disclose and therefore states in reasonably stable language -- going concern,
covenant compliance, default, restructuring, listing status, control
weaknesses, dividend and rating actions.

Out: sentiment ("challenging environment"), forward-looking guidance, and
anything whose wording is a matter of house style rather than disclosure
obligation. Those vary far more between filers than between healthy and
distressed ones, so they measure the drafting lawyer, not the credit.

## Specificity is measured, not declared

`RiskSignalDefinition.specificity` is set from each signal's measured rate in
filings that preceded a bankruptcy petition against its rate in filings that
did not, over the 238-filing Phase 10 corpus (`docs/nlp_risk_signals.md` §6).
The rule: lift >= 2.5 is `HIGH`, 1.5-2.5 is `MODERATE`, below 1.5 is `LOW`,
applied wherever at least 10 event filings carry the signal; below that count
the value is a judgement and the doc says so.

Three of the twelve first-pass declarations were wrong, and the corrections
matter more than the agreements. `MATERIAL_WEAKNESS` was declared `HIGH` and
measures a lift of **1.16** -- it appears in 13.6% of event filings and 11.7%
of comparison filings, so as a *credit* signal it is close to noise, whatever
its value as a reason to distrust the numbers. `COVENANT_BREACH` was declared
`HIGH` and measures 2.21. Only `COVENANT_WAIVER_OR_AMENDMENT` moved upward.

Also out, on purpose: **counting distress words**. A "risk vocabulary density"
score over Item 1A is the classic version of this layer, and it mostly measures
how long the risk factors are. This project already refuses composite scores
whose inputs cannot be inspected (D-022), and the same objection applies here.

## Patterns are written against the normalised view

`normalize.match_view` lower-cases and folds typographic punctuation without
moving any character, so every pattern below is plain lower-case ASCII and
every offset still indexes the original document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode, Specificity

CATALOG_VERSION = "1.0"


@dataclass(frozen=True)
class SignalPattern:
    """One regular expression and the identity it fires under."""

    pattern_id: str
    regex: str
    #: Compiled lazily by the module-level loop below, never per call.
    compiled: re.Pattern[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "compiled", re.compile(self.regex))


@dataclass(frozen=True)
class RiskSignalDefinition:
    """A signal: its patterns, its meaning, and how much it proves alone."""

    code: RiskSignalCode
    label: str
    description: str
    specificity: Specificity
    patterns: tuple[SignalPattern, ...]
    #: Which moods to emit. Every signal emits `ASSERTED`; most also emit
    #: `NEGATED`, because an explicit denial ("we were in compliance with all
    #: covenants") is worth showing. `HYPOTHETICAL` is emitted for none of
    #: them by default -- that is the whole point of the gate -- but the
    #: extractor can be asked for it.
    emit: frozenset[Assertion] = frozenset({Assertion.ASSERTED, Assertion.NEGATED})
    #: A phrase that must also appear somewhere in the sentence for the match
    #: to count. Used where a trigger is too generic on its own.
    requires_context: str | None = None
    #: A phrase that, if present anywhere in the sentence, **suppresses** the
    #: match. This is for a failure the assertion gate cannot catch, because
    #: the sentence really is in the indicative: a filing describing its credit
    #: agreement's own terms ("termination events customary for facilities of
    #: this type, including breaches of covenants") states a fact about the
    #: contract, not about the filer's compliance with it.
    excludes_context: str | None = None
    compiled_context: re.Pattern[str] | None = field(init=False, default=None, repr=False)
    compiled_exclusion: re.Pattern[str] | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if self.requires_context is not None:
            object.__setattr__(self, "compiled_context", re.compile(self.requires_context))
        if self.excludes_context is not None:
            object.__setattr__(self, "compiled_exclusion", re.compile(self.excludes_context))


def _p(pattern_id: str, regex: str) -> SignalPattern:
    return SignalPattern(pattern_id=pattern_id, regex=regex)


#: Debt instruments and agreements, reused by several patterns. Keeping it in
#: one constant is what stops "covenant" patterns and "default" patterns from
#: drifting apart as either is edited.
_DEBT = (
    r"(?:credit (?:agreement|facility|agreements|facilities)|indenture|\bnotes?\b|\bloan\b|term loan|"
    r"revolv(?:er|ing)|debentures?|senior secured|\bdebt\b|borrowings?)"
)

#: Prose that describes a debt agreement's **terms** rather than the filer's
#: compliance with them. The assertion gate cannot catch these, because they
#: are in the indicative and do state a fact -- about the contract. "The A/R
#: Facility includes termination events customary for facilities of this type
#: ... including, among other things, breaches of covenants" is a description
#: of a credit agreement, not a disclosure that a covenant was breached.
#: Measured on the Phase 10 development sample, this shape produced 3 of the
#: 11 false positives found.
_CONTRACT_TERMS = (
    r"\bcustomar(?:y|ily)\b|\bprovides? (?:that|for)\b|\btermination events\b"
    r"|\bevents? of default (?:include|including)\b|\bas long as\b"
    r"|\brequires?[^.]{0,40}\bthat we maintain\b"
)

#: Definitional prose quoting an accounting standard rather than describing
#: this filer. ASU 2014-15's own wording -- "substantial doubt ... exists when
#: ... it is probable that **the entity** will be unable to meet its
#: obligations" -- is a definition, and filings quote it verbatim.
_DEFINITIONAL = r"\b(?:an|the) entity\b|\bis defined as\b|\basu \d|\basc \d"

CATALOG: tuple[RiskSignalDefinition, ...] = (
    RiskSignalDefinition(
        code=RiskSignalCode.GOING_CONCERN_DOUBT,
        excludes_context=_DEFINITIONAL,
        label="Going-concern doubt",
        description=(
            "Management or the auditor states substantial doubt about the filer's ability to "
            "continue as a going concern. Under ASU 2014-15 this disclosure is mandatory once "
            "the conditions are met, so its wording is unusually stable across filers -- which "
            "is what makes it the most reliable narrative signal in the catalog."
        ),
        specificity=Specificity.HIGH,
        patterns=(
            # The statutory phrasing, in the orders filers actually use.
            _p(
                "gc.substantial_doubt",
                r"substantial doubt[^.]{0,80}?(?:ability to )?continue as a \bgoing concern\b",
            ),
            _p(
                "gc.doubt_exists",
                r"(?:substantial doubt (?:exists|existed)|there exists? substantial doubt)",
            ),
            _p("gc.raise_doubt", r"(?:raise|create)[sd]?\s+substantial doubt"),
            # The auditor's report, which is a separate disclosure from
            # management's own conclusion and can appear without it.
            _p(
                "gc.auditor_paragraph",
                r"\bgoing concern\b[^.]{0,40}(?:uncertainty|explanatory) paragraph",
            ),
            _p(
                "gc.auditor_opinion",
                r"(?:report|opinion)[^.]{0,80}\bgoing concern\b (?:uncertainty|qualification)",
            ),
            # "our ability to continue as a going concern is dependent upon..."
            _p("gc.dependent_upon", r"continue as a \bgoing concern\b is dependent"),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.COVENANT_BREACH,
        excludes_context=_CONTRACT_TERMS,
        label="Covenant breach",
        description=(
            "The filer states it was not in compliance with a debt covenant. Distinguished from "
            "the far more common hypothetical ('if we fail to comply') by the assertion gate, "
            "and from its own denial ('we were in compliance with all covenants') by the "
            "negation cues -- both of which appear in the same filings."
        ),
        specificity=Specificity.MODERATE,
        patterns=(
            # The bare trigger also matched "we were not in compliance with
            # NYSE continued listing standards", which is a DELISTING_NOTICE
            # and not a covenant breach at all -- 2 of the 11 false positives
            # in the development sample. A debt or covenant context is now
            # required.
            _p(
                "cv.not_in_compliance",
                rf"(?:was|were|are|is|not been|have not been)\s+not in compliance"
                rf"[^.]{{0,60}}(?:covenant|{_DEBT})",
            ),
            _p(
                "cv.not_comply",
                r"(?:did not|do not|does not|failed to)\s+(?:comply with|satisfy|meet)[^.]{0,60}covenant",
            ),
            _p(
                "cv.breach",
                r"(?:breach(?:ed|es)?|violat(?:ed|ion|ions)) (?:of |the )?[^.]{0,40}covenant",
            ),
            _p("cv.covenant_violation", r"covenant (?:breach|violation|default|non-?compliance)"),
            _p("cv.non_compliance", r"non-?compliance with[^.]{0,40}covenant"),
            # The *affirmative* statement, which exists so `Assertion.NEGATED`
            # is reachable for this code at all. The catalog matches the topic
            # and the assertion gate decides the polarity -- but that only
            # works if a pattern also matches the positive wording. The
            # lookbehind keeps a real breach ("were **not** in compliance with
            # the leverage covenant") out, so the two patterns never race to
            # describe the same sentence.
            _p("cv.compliance_statement", r"(?<!not )\bin compliance with\b[^.]{0,40}covenant"),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.COVENANT_WAIVER_OR_AMENDMENT,
        excludes_context=_CONTRACT_TERMS,
        label="Covenant waiver or amendment",
        description=(
            "A covenant was waived, or an agreement amended, to avoid or cure a breach. Often "
            "the only visible trace of a breach that was resolved before the filing date, and "
            "for monitoring purposes it is nearly as informative as the breach itself."
        ),
        specificity=Specificity.HIGH,
        patterns=(
            _p(
                "wv.obtained_waiver",
                r"(?:obtain(?:ed|ing)?|receiv(?:ed|ing)|sought|seek(?:ing)?|negotiat(?:ed|ing))\s+(?:a |the |certain )?\bwaivers?\b",
            ),
            _p(
                "wv.waiver_of_covenant",
                r"\bwaivers?\b (?:of|from|under)[^.]{0,60}(?:covenant|default|compliance)",
            ),
            _p(
                "wv.amend_to_avoid",
                rf"amend(?:ed|ment|ments)?[^.]{{0,80}}{_DEBT}[^.]{{0,80}}(?:covenant|compliance|default)",
            ),
            _p("wv.covenant_relief", r"\bcovenant\b (?:relief|holiday|suspension|amendment)"),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION,
        excludes_context=_CONTRACT_TERMS,
        label="Default or acceleration",
        description=(
            "An event of default has occurred, or debt has been accelerated, or long-term debt "
            "has been reclassified as current because a default makes it callable. The "
            "reclassification is worth catching separately: it is an accounting consequence "
            "that shows up in the balance sheet this layer's Phase 6 sibling already reads."
        ),
        specificity=Specificity.HIGH,
        patterns=(
            # Was `(?:has|have|had|occurred|existed|exists)`, which matched a
            # facility's own terms ("...when availability falls below $50
            # million or an event of default exists") and also survived "events
            # of default have **not** occurred", because that negation follows
            # the trigger where the adjacency rule looks before it. Requiring
            # an adjacent completed verb fixes both at once.
            _p(
                "df.event_of_default",
                r"(?:an? |the )?events? of default (?:has|have) occurred"
                r"|(?:an? |the )?events? of default (?:is|are) continuing",
            ),
            _p(
                "df.default_occurred",
                r"(?:we|the company)[^.]{0,40}(?:defaulted|are in default|is in default|was in default|were in default)",
            ),
            _p("df.notice_of_default", r"notice of (?:default|acceleration)"),
            _p(
                "df.accelerated", rf"{_DEBT}[^.]{{0,60}}(?:has been|have been|were|was) accelerated"
            ),
            _p(
                "df.reclassified_current",
                r"reclassif(?:ied|ication)[^.]{0,80}(?:as|to) (?:a )?current (?:liabilit|maturit|portion)",
            ),
            _p(
                "df.missed_payment",
                r"(?:fail(?:ed|ure) to (?:make|pay)|did not (?:make|pay)|elected to defer)[^.]{0,60}(?:interest|principal) payment",
            ),
            _p("df.grace_period", r"(?:30|thirty|60|sixty)-day grace period"),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.DEBT_RESTRUCTURING,
        label="Debt restructuring under way",
        description=(
            "An out-of-court restructuring is in progress: a forbearance agreement, an exchange "
            "offer, a restructuring support agreement, or the engagement of restructuring "
            "advisers. In credit terms this is the step immediately before a filing, and it is "
            "usually disclosed weeks or months earlier."
        ),
        specificity=Specificity.HIGH,
        patterns=(
            _p("rs.forbearance", r"forbearance (?:agreement|period)"),
            _p("rs.rsa", r"restructuring support agreement"),
            _p("rs.exchange_offer", r"(?:exchange offer|debt exchange|distressed exchange)"),
            _p(
                "rs.advisers",
                r"(?:engaged|retained|hired)[^.]{0,60}(?:restructuring|financial) (?:advisors?|advisers?)",
            ),
            _p(
                "rs.restructuring_of_debt",
                rf"restructur(?:e|ing)[^.]{{0,40}}(?:our |its |the )?(?:indebtedness|capital structure|{_DEBT})",
            ),
            _p(
                "rs.negotiations_with_lenders",
                r"(?:negotiations|discussions) with[^.]{0,50}(?:lenders|noteholders|creditors|holders of)",
            ),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.BANKRUPTCY_CONTEMPLATED,
        label="Bankruptcy contemplated or filed",
        description=(
            "Bankruptcy protection is contemplated, prepared for, or already filed. A filer "
            "naming chapter 11 as something it may seek -- rather than describing what chapter "
            "11 would mean for its investors -- is stating an intention, and the assertion gate "
            "is what keeps the two apart."
        ),
        specificity=Specificity.HIGH,
        patterns=(
            _p(
                "bk.filed_petition",
                r"(?:filed|commenced)[^.]{0,60}(?:voluntary )?(?:petitions?|cases?) (?:for relief )?under chapter (?:7|11)",
            ),
            _p(
                "bk.seek_protection",
                r"(?:seek|sought|pursue|consider(?:ing)?|evaluat(?:e|ing)|prepar(?:e|ing))[^.]{0,60}(?:protection under|relief under|filing under)[^.]{0,30}(?:chapter (?:7|11)|bankruptcy code)",
            ),
            _p("bk.prepackaged", r"(?:pre-?packaged|pre-?arranged) (?:plan|bankruptcy|chapter 11)"),
            _p("bk.debtor_in_possession", r"debtor-?in-?possession"),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.LIQUIDITY_SHORTFALL,
        excludes_context=_DEFINITIONAL,
        label="Liquidity shortfall",
        description=(
            "The filer states that its own resources may not be sufficient to meet its "
            "obligations. Narrow by design: this is a statement about the filer's cash, not "
            "about credit markets in general, because 'capital markets may become unavailable' "
            "appears in essentially every 10-K."
        ),
        specificity=Specificity.MODERATE,
        patterns=(
            # Bare `capital` matched "our reduced capital program in 2016 will
            # not be sufficient to offset production declines" -- a statement
            # about capex against output, not about meeting obligations.
            _p(
                "lq.not_sufficient",
                r"(?:cash|liquidity|resources|funds|capital resources|working capital|"
                r"borrowing capacity)[^.]{0,60}(?:will not|are not|is not|may not) be sufficient",
            ),
            _p("lq.insufficient", r"\binsufficient\b (?:liquidity|cash|funds|capital|resources)"),
            _p(
                "lq.unable_to_meet",
                r"unable to (?:meet|satisfy|fund)[^.]{0,40}(?:obligations|commitments|liabilities|requirements)",
            ),
            _p(
                "lq.substantial_need",
                r"(?:immediate|urgent|substantial) need for (?:additional )?(?:capital|liquidity|financing)",
            ),
            _p(
                "lq.drew_down_revolver",
                r"(?:drew|drawn|borrowed)[^.]{0,50}(?:full|entire|remaining|available)[^.]{0,40}(?:revolv|credit facility)",
            ),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.MATERIAL_WEAKNESS,
        label="Material weakness in internal control",
        description=(
            "A material weakness in internal control over financial reporting was identified. "
            "It bears on credit indirectly but bears on *this pipeline* directly: it is a "
            "stated reason to trust the filing's own numbers less, and every ratio and feature "
            "downstream is computed from them."
        ),
        specificity=Specificity.LOW,
        patterns=(
            _p(
                "mw.identified",
                r"(?:identified|concluded|determined)[^.]{0,80}material weakness(?:es)?",
            ),
            _p("mw.existed", r"material weakness(?:es)? (?:in|existed|exists|was|were|identified)"),
            _p(
                "mw.not_effective",
                r"(?:internal control|disclosure controls)[^.]{0,80}(?:were|was|are|is) not effective",
            ),
            _p(
                "mw.restatement",
                r"(?:restate(?:d|ment)|revised)[^.]{0,60}(?:previously issued|prior period|historical)[^.]{0,40}financial statements",
            ),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.DIVIDEND_SUSPENSION,
        label="Dividend suspended or cut",
        description=(
            "The dividend was suspended, eliminated or reduced. A discretionary cash outflow "
            "stopping is one of the earliest actions a board takes under strain, and it "
            "usually precedes anything visible in a covenant disclosure."
        ),
        specificity=Specificity.MODERATE,
        patterns=(
            _p(
                "dv.suspended",
                r"(?:suspend(?:ed|ing)?|eliminat(?:ed|ing)|discontinu(?:ed|ing)|ceased paying)[^.]{0,40}(?:our |the |quarterly |common stock )?dividend",
            ),
            _p(
                "dv.no_longer_pay",
                r"(?:no longer (?:pay|declare)|will not (?:pay|declare))[^.]{0,30}dividend",
            ),
            _p(
                "dv.reduced",
                r"\b(?:reduc(?:ed|tion)|cut)\b[^.]{0,30}(?:in |of |our |the )?(?:quarterly )?\bdividend\b",
            ),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.DELISTING_NOTICE,
        label="Delisting notice",
        description=(
            "An exchange notified the filer that it no longer meets continued listing "
            "standards. Distinct from the generic 'our stock price may decline' risk factor, "
            "which is why the pattern requires the exchange or the notice, not the word."
        ),
        specificity=Specificity.HIGH,
        patterns=(
            _p(
                "dl.notice",
                r"(?:notice|notification|letter)[^.]{0,80}(?:nyse|nasdaq|new york stock exchange|the exchange)[^.]{0,80}(?:non-?compliance|not in compliance|listing standard|minimum)",
            ),
            _p(
                "dl.non_compliance_listing",
                r"(?:not in compliance|non-?compliance|failed to (?:satisfy|meet))[^.]{0,60}(?:continued )?listing (?:standards?|requirements?|rules?|criteria|criterion)",
            ),
            _p(
                "dl.delisted",
                r"(?:was|were|has been|have been|will be) (?:de-?listed|suspended from (?:trading|listing))",
            ),
            _p(
                "dl.transferred_otc",
                r"(?:transferred|moved|began trading)[^.]{0,50}(?:over-?the-?counter|otc (?:markets|pink))",
            ),
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.CREDIT_RATING_DOWNGRADE,
        label="Credit rating downgrade",
        description=(
            "A rating agency downgraded the filer. An external party's assessment, so it is "
            "genuinely independent evidence rather than the filer's own characterisation -- "
            "but it is also a lagging one, which is why its specificity is moderate."
        ),
        specificity=Specificity.MODERATE,
        patterns=(
            _p(
                "rt.downgraded",
                r"(?:downgrad(?:ed|e|es|ing)|lowered)[^.]{0,80}(?:our|the company's|its)?[^.]{0,30}(?:credit )?ratings?",
            ),
            _p(
                "rt.agency_action",
                r"(?:moody's|standard & poor's|s&p|fitch)[^.]{0,80}(?:downgrad|lowered|reduced|negative outlook|credit watch)",
            ),
            # `(?:below|non-?)investment grade` was removed: being *rated*
            # below investment grade is a standing condition, not a downgrade
            # event, and this code is about the event. Kodak's "the current
            # non-investment grade credit ratings have resulted in..." is a
            # true statement that this signal should not be making.
        ),
    ),
    RiskSignalDefinition(
        code=RiskSignalCode.ASSET_IMPAIRMENT,
        label="Asset impairment recognised",
        description=(
            "An impairment was recognised. Kept in the catalog although it is common in "
            "perfectly healthy filers -- Coca-Cola's and UPS's MD&A each discuss impairment "
            "charges more than a dozen times -- because it is real evidence when it is large "
            "or repeated. Its measured specificity is what tells a consumer to corroborate it "
            "rather than act on it; this is the catalog's worked example of a signal that is "
            "worth reporting and not worth trusting alone."
        ),
        specificity=Specificity.LOW,
        patterns=(
            _p(
                "im.recorded",
                r"\b(?:recorded|recognized|recognised|incurred|took)\b[^.]{0,60}\bimpairment\b",
            ),
            _p(
                "im.goodwill",
                r"\b(?:goodwill|asset|long-?lived|full cost ceiling)\b[^.]{0,30}\bimpairment\b",
            ),
            _p(
                "im.write_down",
                r"(?:write-?(?:down|off)|wrote (?:down|off))[^.]{0,60}(?:goodwill|assets|carrying value)",
            ),
        ),
        # "impairment" appears in accounting-policy prose constantly; requiring
        # a charge, an amount or a period keeps the policy discussion out.
        requires_context=r"(?:\$|million|billion|charge|expense|during|year ended|quarter)",
    ),
)

CATALOG_BY_CODE: dict[RiskSignalCode, RiskSignalDefinition] = {
    definition.code: definition for definition in CATALOG
}


def definition_for(code: RiskSignalCode) -> RiskSignalDefinition:
    return CATALOG_BY_CODE[code]
