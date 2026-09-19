"""Build the analyst workspace's database from the real corpus.

Records every assessment the pipeline produces and **nothing else**: no
drafts, no reviews. That is deliberate. The workspace is meant to demonstrate
the analyst's own workflow, so every draft it shows and every decision it
records should be one the person at the keyboard actually made. A store
pre-seeded with synthetic reviews would put words in an analyst's mouth on
the first screen -- which is the exact failure the review layer exists to
prevent.

`phase13_audit.py` is the integrity measurement and seeds harness reviews on
purpose; this is the demo spine.

    uv run python scripts/build_workspace_db.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase13_audit import build_assessments  # noqa: E402

from credit_risk_copilot.logging_config import configure_logging  # noqa: E402
from credit_risk_copilot.review import ReviewStore  # noqa: E402
from credit_risk_copilot.workspace import DEFAULT_DB  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    if DEFAULT_DB.exists():
        # The store refuses edits by design, so rebuilding means starting from
        # empty rather than reconciling.
        DEFAULT_DB.unlink()

    assessments = build_assessments()
    with ReviewStore(DEFAULT_DB) as store:
        for assessment in assessments:
            store.record_assessment(assessment)
        counts = store.counts()
        companies = len({a.cik for a in assessments})

    logger.info(
        "Wrote %s: %d assessments over %d companies (%d drafts, %d reviews)",
        DEFAULT_DB,
        counts["assessment"],
        companies,
        counts["draft"],
        counts["review"],
    )
    print(f"{DEFAULT_DB}: {counts['assessment']} assessments, {companies} companies")


if __name__ == "__main__":
    main()
