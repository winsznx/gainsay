"""Write the read-only ledger snapshot the deployed site serves.

The site shows results; checks run where the keys and the CourtListener
quota are. The snapshot is a consistent copy of the ledger (SQLite's backup
API, so a run writing at the same time can't tear it) with the cached
CourtListener responses and Claude requests removed. It holds public court
filings, citations, findings and traces. It is refused if any value from
.env appears in it.

    .venv/bin/python scripts/publish_snapshot.py
"""

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "data" / "gainsay.sqlite"
SNAPSHOT = REPO_ROOT / "deploy" / "gainsay-demo.sqlite"
DROPPED_TABLES = ("api_responses", "llm_responses")
MIN_SECRET_LENGTH = 12


def secrets(env: Path = REPO_ROOT / ".env") -> list[bytes]:
    if not env.exists():
        return []
    values = []
    for line in env.read_text().splitlines():
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if key.strip() and not key.lstrip().startswith("#") and len(value) >= MIN_SECRET_LENGTH:
            values.append(value.encode())
    return values


def main() -> int:
    if not LEDGER.exists():
        print(f"error: no ledger at {LEDGER.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1
    staging = SNAPSHOT.with_suffix(".staging")
    staging.unlink(missing_ok=True)
    source = sqlite3.connect(LEDGER)
    target = sqlite3.connect(staging)
    source.backup(target)
    source.close()
    existing = {row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in DROPPED_TABLES:
        if table in existing:
            target.execute(f"DELETE FROM {table}")
    target.commit()
    target.execute("VACUUM")
    target.close()

    data = staging.read_bytes()
    leaked = sum(secret in data for secret in secrets())
    if leaked:
        staging.unlink()
        print(f"error: {leaked} value(s) from .env appear in the snapshot; nothing was written", file=sys.stderr)
        return 1
    staging.replace(SNAPSHOT)
    conn = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)
    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    findings = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    conn.close()
    print(f"wrote {SNAPSHOT.relative_to(REPO_ROOT)}: {len(data) / 1e6:.1f} MB, {runs} runs, {findings} findings, "
          f"no .env values found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
