"""Check every exhibit RECAP holds for one docket entry, each as a filing of its own.

One request lists the entry's documents (cached in the ledger afterwards);
each exhibit is fetched, extracted and checked like a main document, and
appears as "ECF N-M" on the site.

    (set -a; source .env; set +a; .venv/bin/python scripts/check_exhibits.py --entry 29)
"""

import argparse
import logging
import sys
from pathlib import Path

from gainsay.blocklist import BlocklistedDocument
from gainsay.cache import CachedCourtListener
from gainsay.cap import Cap
from gainsay.courtlistener import BudgetExhausted, CourtListenerClient, CourtListenerError
from gainsay.dockets import DEFAULT_DOCKET_CONFIG, load_docket_config, resolve_docket
from gainsay.filings import FetchError
from gainsay.ledger import connect
from gainsay.pdf_text import TextUnavailable
from gainsay.proposition import ClaudeJudge, MissingCredentials, anthropic_client
from gainsay.report import load_run
from gainsay.tracing import Tracing
from gainsay.version import run_version
from gainsay.watch import check_exhibits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docket", type=Path, default=DEFAULT_DOCKET_CONFIG)
    parser.add_argument("--entry", type=int, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        claude = anthropic_client()
        client = CourtListenerClient()
    except (MissingCredentials, CourtListenerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    conn = connect()
    api = CachedCourtListener(conn)
    tracing = Tracing("check-exhibits")
    judge = ClaudeJudge(conn, tracing.wrap(claude))
    status = 0
    try:
        docket = resolve_docket(conn, client, load_docket_config(args.docket))
        results = check_exhibits(conn, client, api, judge, tracing, docket, args.entry, run_version(), Cap())
        if not results:
            print(f"ECF {args.entry}: no exhibits left to check")
        for attachment, result in results:
            report = load_run(conn, result.run_id)
            print(f"ECF {args.entry}-{attachment}: run {result.run_id} {result.status}. {report.headline if report else ''}")
            if result.status == "paused":
                print(f"paused: {result.reason}. Rerun to resume.", file=sys.stderr)
                status = 2
    except BudgetExhausted as exc:
        print(f"paused: {exc}. Rerun when the quota refills.", file=sys.stderr)
        status = 2
    except (BlocklistedDocument, CourtListenerError, FetchError, TextUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        status = 1
    finally:
        tracing.close()
        print(f"CourtListener calls: {client.calls + api.calls}, served from ledger: {api.cache_hits}")
    return status


if __name__ == "__main__":
    sys.exit(main())
