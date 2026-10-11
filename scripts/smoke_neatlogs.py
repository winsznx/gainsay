"""Emit one gainsay.smoke span to Neatlogs to confirm the export path works.

Run with the key from .env loaded into the environment:
    set -a; source .env; set +a; .venv/bin/python scripts/smoke_neatlogs.py
"""

import os
import sys

import neatlogs


def main() -> int:
    if not os.environ.get("NEATLOGS_API_KEY"):
        print("NEATLOGS_API_KEY is not set; load .env first", file=sys.stderr)
        return 1

    neatlogs.init(workflow_name="gainsay-smoke")
    try:
        with neatlogs.trace("gainsay.smoke", kind="WORKFLOW") as span:
            trace_id = span.get_span_context().trace_id
            print(f"trace_id={trace_id:032x}")
    finally:
        neatlogs.flush()
        neatlogs.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
