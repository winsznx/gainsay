"""Fetch one RECAP filing's PDF and text and register it in the ledger.

Defaults to Mata v. Avianca, S.D.N.Y. 1:22-cv-01461, ECF 21: the March 1, 2023
affirmation in opposition, the first filing Gainsay checks.

    set -a; source .env; set +a; .venv/bin/python scripts/fetch_filing.py [--entry N] [--docket CONFIG]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from gainsay.blocklist import BlocklistedDocument, assert_not_blocklisted
from gainsay.courtlistener import CourtListenerClient, CourtListenerError
from gainsay.dockets import DEFAULT_DOCKET_CONFIG, load_docket_config, resolve_docket
from gainsay.filings import FetchError, fetch_filing
from gainsay.ledger import connect, upsert_filing
from gainsay.pdf_text import TextUnavailable
from gainsay.tracing import Tracing

DEFAULT_ENTRY = 21
PREVIEW_LINES = 40


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docket", type=Path, default=DEFAULT_DOCKET_CONFIG)
    parser.add_argument("--entry", type=int, default=DEFAULT_ENTRY)
    parser.add_argument("--attachment", type=int, help="fetch this attachment (exhibit) instead of the main document")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    config = load_docket_config(args.docket)
    try:
        assert_not_blocklisted(config.court, config.docket_number, args.entry)
        client = CourtListenerClient()
    except (BlocklistedDocument, CourtListenerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    conn = connect()
    tracing = Tracing("fetch-filing")
    try:
        with tracing.span(
            "gainsay.fetch_filing",
            court=config.court,
            docket_number=config.docket_number,
            entry_number=args.entry,
        ):
            docket = resolve_docket(conn, client, config)
            manifest, text = fetch_filing(client, docket, args.entry, args.attachment)
            upsert_filing(conn, manifest)
    except (BlocklistedDocument, CourtListenerError, FetchError, TextUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        tracing.close()
        print(f"CourtListener calls: {client.calls}")

    print(json.dumps(manifest, indent=2))
    print(f"--- first {PREVIEW_LINES} lines of {manifest['text_path']} ---")
    print("\n".join(text.splitlines()[:PREVIEW_LINES]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
