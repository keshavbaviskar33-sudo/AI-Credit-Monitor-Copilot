"""A deliberately over-broad sweep, used only to give recall a denominator.

Precision is easy to measure: look at what the layer emitted and count how much
of it is right. Recall is not, because its denominator is *every true instance
in the corpus*, and nobody is going to read 240 filings sentence by sentence.

The standard honest compromise is pooling: run a second matcher that is far
broader than the production one, hand-label everything it surfaces, and measure
what fraction of the true instances in that pool the production catalog caught.
That gives **recall relative to the sweep's own reach** -- an upper bound on
the denominator, not the true one -- and the number must always be reported
with that qualification. A signal phrased in words neither matcher contains is
invisible to both, and no amount of arithmetic here will reveal it.

The sweep is therefore built on bare topic keywords with no assertion gate, no
context requirement and no polarity: "covenant", "default", "going concern",
"impairment". It is expected to surface mostly boilerplate. That is the point
-- the boilerplate is what gets labelled `boilerplate` and dropped from the
denominator, and what remains is a defensible set of true instances that were
found by something other than the rules being scored.
"""

from __future__ import annotations

import logging
import random
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from credit_risk_copilot.extraction.base import DocumentExtractionError
from credit_risk_copilot.extraction.html_extractor import HtmlDocumentExtractor
from credit_risk_copilot.extraction.models import DocumentSource, ExtractedDocument
from credit_risk_copilot.nlp.extract import NARRATIVE_SECTIONS, extract_from_text
from credit_risk_copilot.nlp.models import Assertion, RiskSignalCode
from credit_risk_copilot.nlp.normalize import match_view
from credit_risk_copilot.nlp.segment import split_sentences

#: Bare topic keywords, one per catalog code. No moods, no context, no
#: polarity -- if the word is in the sentence, the sentence is a candidate.
SWEEP_TERMS: dict[RiskSignalCode, str] = {
    RiskSignalCode.GOING_CONCERN_DOUBT: r"going concern|substantial doubt",
    RiskSignalCode.COVENANT_BREACH: r"covenant",
    RiskSignalCode.COVENANT_WAIVER_OR_AMENDMENT: r"waiver|waive",
    RiskSignalCode.DEBT_DEFAULT_OR_ACCELERATION: r"default|accelerat",
    RiskSignalCode.DEBT_RESTRUCTURING: r"restructur|forbearance|exchange offer",
    RiskSignalCode.BANKRUPTCY_CONTEMPLATED: r"bankrupt|chapter 11|chapter 7",
    RiskSignalCode.LIQUIDITY_SHORTFALL: r"liquidity|sufficient cash",
    RiskSignalCode.MATERIAL_WEAKNESS: r"material weakness|internal control",
    RiskSignalCode.DIVIDEND_SUSPENSION: r"dividend",
    RiskSignalCode.DELISTING_NOTICE: r"delist|listing standard|nyse|nasdaq",
    RiskSignalCode.CREDIT_RATING_DOWNGRADE: r"downgrad|credit rating",
    RiskSignalCode.ASSET_IMPAIRMENT: r"impairment|write-down|wrote off",
}

logger = logging.getLogger(__name__)

_COMPILED = {code: re.compile(pattern) for code, pattern in SWEEP_TERMS.items()}

#: Candidates drawn per filing, so one verbose filer cannot dominate the pool.
_PER_FILING = 3


def sweep_candidates(
    corpus: Sequence[Mapping[str, Any]], *, limit: int, seed: int
) -> list[dict[str, Any]]:
    """Candidate sentences for the recall pool, with the catalog's own verdict.

    Each row records whether the production catalog emitted an **asserted**
    signal of that code for that exact sentence (`caught_by_catalog`), so the
    labeller decides only whether the sentence is a true instance and the
    arithmetic follows from that -- rather than the labeller being asked to
    judge the thing being measured.
    """
    rng = random.Random(seed)
    extractor = HtmlDocumentExtractor()
    candidates: list[dict[str, Any]] = []
    skipped: list[str] = []

    # Plain rows rather than a DataFrame: this module iterates and never
    # aggregates, so taking pandas as a dependency of the library would buy
    # nothing and cost the strict-typing contract that `src/` holds to.
    order = list(range(len(corpus)))
    rng.shuffle(order)

    for index in order:
        if len(candidates) >= limit:
            break
        row = corpus[index]
        path = Path(str(row["html_path"]).replace("\\", "/"))
        if not path.exists():
            continue
        try:
            document = extractor.extract(
                path.read_bytes(),
                DocumentSource(
                    uri=str(path),
                    media_type="text/html",
                    cik=int(row["cik"]),
                    accession=str(row["accession"]),
                    form=str(row.get("form") or "10-K"),
                    filed=(str(row["filed"]) if row.get("filed") else None),
                ),
            )
        # Deliberately narrow. An unparseable filing is a fact about the
        # corpus and is skipped; a `KeyError` or a `TypeError` is a fact about
        # this code and must not be silently absorbed into a smaller
        # denominator. A blanket `except Exception` here did exactly that --
        # it swallowed a missing dictionary key and returned an empty sweep,
        # which would have read as "the corpus has no candidates".
        except (DocumentExtractionError, OSError, ValueError) as error:
            skipped.append(f"{row.get('accession')}: {error}")
            continue

        found = _candidates_in(document, str(row["accession"]), str(row["company"]))
        rng.shuffle(found)
        candidates.extend(found[:_PER_FILING])

    if skipped:
        logger.warning(
            "recall sweep skipped %d unreadable filing(s): %s", len(skipped), skipped[:3]
        )
    rng.shuffle(candidates)
    return candidates[:limit]


def _candidates_in(
    document: ExtractedDocument, accession: str, company: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section_id in NARRATIVE_SECTIONS:
        body = document.section_text(section_id)
        if body is None:
            continue
        view = match_view(body)
        for start, end in split_sentences(body):
            sentence_view = view[start:end]
            for code, pattern in _COMPILED.items():
                if pattern.search(sentence_view) is None:
                    continue
                emitted = extract_from_text(body[start:end])
                out.append(
                    {
                        "verdict": "",  # true_signal | boilerplate | unrelated
                        "note": "",
                        "code": code.value,
                        "accession": accession,
                        "company": company,
                        "section_id": section_id,
                        "caught_by_catalog": any(
                            signal.code is code and signal.assertion is Assertion.ASSERTED
                            for signal in emitted
                        ),
                        "quote": body[start:end].replace("\n", " "),
                    }
                )
    return out
