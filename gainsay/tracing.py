"""neatlogs setup that never takes the run down with it.

Tracing is observability, not part of the result. If the SDK can't start, the
run continues untraced and says so on stderr.
"""

import logging
import os
from contextlib import contextmanager, nullcontext
from typing import Any, Iterator

import neatlogs

logger = logging.getLogger(__name__)


class Tracing:
    def __init__(self, workflow_name: str):
        self.enabled = False
        if not os.environ.get("NEATLOGS_API_KEY"):
            logger.warning("NEATLOGS_API_KEY is not set, running without tracing")
            return
        try:
            neatlogs.init(workflow_name=workflow_name)
        except Exception as exc:
            logger.warning("neatlogs init failed, running without tracing: %s", exc)
            return
        self.enabled = True

    @contextmanager
    def span(self, name: str, kind: str = "WORKFLOW", **attributes: Any) -> Iterator[Any]:
        context = (
            neatlogs.trace(name, kind=kind, **attributes)
            if self.enabled
            else nullcontext()
        )
        with context as span:
            yield span

    def close(self) -> None:
        if not self.enabled:
            return
        try:
            neatlogs.flush()
            neatlogs.shutdown()
        except Exception as exc:
            logger.warning("neatlogs flush failed, spans from this run may be lost: %s", exc)
