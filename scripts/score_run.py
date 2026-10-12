"""Score a check run against a court's own findings.

Run only after the check run is finished. The ruling the answer key quotes
(Mata ECF 54 by default, or Gauthier ECF 48 with its key) is fetched here
for scoring and nowhere else; the agent's fetch path refuses it.

    set -a; source .env; set +a; .venv/bin/python scripts/score_run.py RUN_ID [--key scoring/gauthier_answer_key.json]
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from gainsay.courtlistener import CourtListenerClient, CourtListenerError
from gainsay.ledger import connect, now
from gainsay.report import load_run
from gainsay.scoring import (
    ANSWER_KEY_PATH,
    RESULTS_DIR,
    AnswerKeyError,
    fetch_answer_source,
    load_answer_key,
    score_run,
    summarize,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id", type=int)
    parser.add_argument("--key", type=Path, default=ANSWER_KEY_PATH, help="answer key JSON")
    args = parser.parse_args()

    report = load_run(connect(), args.run_id)
    if report is None:
        print(f"error: no run {args.run_id} in the ledger", file=sys.stderr)
        return 1
    key = json.loads(args.key.read_text())
    scored = key["scored_filing"]
    if (report.filing["docket_id"], report.filing["entry_number"]) != (scored["docket_id"], scored["entry_number"]):
        print("error: the answer key scores a different filing than this run checked", file=sys.stderr)
        return 1

    try:
        source = key["source"]
        text = fetch_answer_source(CourtListenerClient(), source["docket_id"], source["entry_number"])
        cases = load_answer_key(text, args.key)
        scores = score_run(report, cases)
    except (AnswerKeyError, CourtListenerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    summary = summarize(scores)
    artifact = {
        "run_id": args.run_id,
        "run_version": report.run["version"],
        "scored_at": now(),
        "answer_key": str(args.key.resolve().relative_to(ANSWER_KEY_PATH.parent.parent)),
        "summary": summary,
        "cases": [
            {**asdict(s), "case_status": s.case_status, "outcome": s.outcome, "agrees_with_court": s.agrees_with_court}
            for s in scores
        ],
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"run-{args.run_id}-score.json"
    path.write_text(json.dumps(artifact, indent=2) + "\n")

    print(f"Run {args.run_id} ({report.run['version']}) against ECF {source['entry_number']}")
    print(f"{'case':46} {'court found':24} {'gainsay':32} existence")
    for s in scores:
        agrees = {True: "agrees", False: "disagrees", None: "undecided"}[s.agrees_with_court]
        print(f"{s.case_name[:46]:46} {s.court_finding:24} {(s.case_status or 'Incomplete')[:32]:32} {s.outcome} ({agrees})")
    print(
        f"existence: precision {summary['precision']:.2f}, recall {summary['recall']:.2f} "
        f"({summary['true positive']} TP, {summary['false positive']} FP, {summary['false negative']} FN, "
        f"{summary['true negative']} TN)"
    )
    print(f"full finding: {summary['agree']} agree, {summary['disagree']} disagree, {summary['undecided']} undecided")
    print(f"saved {path.relative_to(RESULTS_DIR.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
