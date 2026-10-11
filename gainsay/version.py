import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_version() -> str:
    """The commit the checks ran from, marked dirty if tracked files have edits."""
    sha = _git("rev-parse", "--short", "HEAD")
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    return f"{sha}-dirty" if dirty else sha


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
