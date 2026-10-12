"""Write a run's report as Markdown.

    .venv/bin/python scripts/export_report.py RUN_ID [--out reports/]
"""

import argparse
import sys
from pathlib import Path

from gainsay.export import render_markdown
from gainsay.ledger import connect
from gainsay.report import load_run

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id", type=int)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports")
    args = parser.parse_args()
    report = load_run(connect(), args.run_id)
    if report is None:
        print(f"error: no run {args.run_id} in the ledger", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"gainsay-run-{args.run_id}-ecf{report.filing['entry_number']}.md"
    path.write_text(render_markdown(report) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
