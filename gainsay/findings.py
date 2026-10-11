from dataclasses import dataclass, field
from typing import Any

PASS = "pass"
FAIL = "fail"
UNVERIFIABLE = "unverifiable"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Finding:
    check: str
    outcome: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
