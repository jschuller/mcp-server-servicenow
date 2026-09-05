"""MCP tool annotations (readOnlyHint / destructiveHint / idempotentHint / openWorldHint).

Surfaced in ``tools/list`` so clients such as Claude Code can apply their own
permission policies. Annotations are hints, not a security boundary — the
policy middleware and ``--read-only`` are the enforcement layer.
"""

from typing import Any, Dict

READ: Dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

CREATE: Dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

UPDATE: Dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}

DELETE: Dict[str, Any] = dict(UPDATE)

SET_PREF: Dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
