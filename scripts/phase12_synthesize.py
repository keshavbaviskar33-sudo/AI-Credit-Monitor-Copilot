"""Phase 12, live path: draft real notes and measure how often they stay grounded.

`phase12_grounding.py` measures what the validator catches. This measures what
a real model actually does with the prompt -- the rejection rate on drafts
nobody tampered with, which is the number Phase 13's reviewer needs in order to
know how much to trust what they are reading.

It is a separate script because it **costs money and requires credentials**,
and nothing in the test suite or the offline measurement may depend on either.
Each assessment is one call; at the measured prompt size that is roughly four
cents on Claude Opus 5. `--limit` is small by default for that reason.

    uv sync --extra llm
    export ANTHROPIC_API_KEY=...        # or: ant auth login
    uv run python scripts/phase12_synthesize.py --limit 20

Every draft, its verdict and its token usage are written to
`data/processed/phase12/live_drafts.json`, so a later change to the validator
can be re-measured against the same drafts without paying again.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import phase11_assess as p11  # noqa: E402

from credit_risk_copilot.assessment import FilingStamp, assemble_assessment  # noqa: E402
from credit_risk_copilot.logging_config import configure_logging  # noqa: E402
from credit_risk_copilot.modeling.dataset import observations_from_rows  # noqa: E402
from credit_risk_copilot.synthesis import (  # noqa: E402
    AnthropicSynthesisClient,
    SynthesisError,
    synthesize,
)

logger = logging.getLogger(__name__)
OUT_DIR = Path("data/processed/phase12")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=20, help="assessments to draft (each is one paid call)"
    )
    parser.add_argument("--model", default="claude-opus-5")
    args = parser.parse_args()

    configure_logging()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    panel = pd.read_csv(p11.PHASE8_DIR / "observations_primary.csv")
    observations = [
        o
        for o in observations_from_rows(panel.replace({np.nan: None}).to_dict("records"))
        if o.outcome.is_usable
    ]
    scored = p11._out_of_fold(observations)
    per_filing = pd.read_csv(p11.PHASE10_DIR / "nlp_per_filing.csv")
    narratives = p11._narrative_reports(
        pd.read_csv(p11.PHASE10_DIR / "nlp_signals.csv"), per_filing
    )
    by_accession = {o.key.source_accession: i for i, o in enumerate(observations)}

    client = AnthropicSynthesisClient(model=args.model)
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    for accession, narrative in list(narratives.items()):
        if len(records) >= args.limit:
            break
        index = by_accession.get(accession)
        if index is None or index not in scored:
            continue
        observation = observations[index]
        as_of = date.fromisoformat(str(narrative.filed))
        assessment = assemble_assessment(
            cik=observation.key.cik,
            company=observation.key.company,
            as_of=as_of,
            health=p11._health_report(observation),
            health_filing=FilingStamp(accession=accession, form="10-K", filed=as_of),
            explanation=p11._explanation(observation, scored[index]),
            narrative=narrative,
            pipeline_versions={"phase": "12"},
        )
        try:
            result = synthesize(assessment, client)
        except SynthesisError as error:
            # Recorded, never retried: a silent retry would break the one-call
            # accounting this phase is written against.
            errors.append(f"{observation.key.company}: {error}")
            logger.warning("synthesis failed for %s: %s", observation.key.company, error)
            continue
        records.append(json.loads(result.model_dump_json()))
        logger.info(
            "%s: %s (%d findings)",
            result.company,
            "accepted" if result.validation.accepted else "REJECTED",
            len(result.validation.findings),
        )

    accepted = [r for r in records if r["validation"]["accepted"]]
    codes: dict[str, int] = {}
    for record in records:
        for finding in record["validation"]["findings"]:
            codes[finding["code"]] = codes.get(finding["code"], 0) + 1

    summary = {
        "model": args.model,
        "drafts": len(records),
        "failed_calls": errors,
        "accepted": len(accepted),
        "acceptance_rate": round(len(accepted) / len(records), 4) if records else None,
        "finding_counts": dict(sorted(codes.items())),
        "tokens": {
            "input_total": sum(r.get("input_tokens") or 0 for r in records),
            "output_total": sum(r.get("output_tokens") or 0 for r in records),
            "cache_read_total": sum(r.get("cache_read_tokens") or 0 for r in records),
        },
    }
    (OUT_DIR / "live_drafts.json").write_text(
        json.dumps({"summary": summary, "drafts": records}, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
