"""Name what failed below this server without repeating what a library said.

The text of a requests, urllib3, http.client or httpx2 exception can quote
bytes of the response (``InvalidChunkLength(got length b'{"result": ...``,
``BadStatusLine('{"result": ...')``), a header value this server sent
(``InvalidHeader ... header value: '<key>'``) or the request's query string
(``Max retries exceeded with url: /api/...?sysparm_query=...``). So an error
message, a log line and the audit line never get that text: they get the
exception classes, outermost first, and an ``errno`` where there is one. A
class name and a number cannot hold response bytes or a credential.
"""

from __future__ import annotations

from typing import List, Set

MAX_CLASSES = 8


def cause_chain(error: BaseException, limit: int = MAX_CLASSES) -> str:
    """``Outer <- Inner <- Innermost [errno 61]``: the classes, never their text."""
    names: List[str] = []
    seen: Set[int] = set()
    pending: List[BaseException] = [error]
    while pending and len(names) < limit:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        name = type(current).__name__
        number = getattr(current, "errno", None)
        if (
            isinstance(current, OSError)
            and isinstance(number, int)
            and not isinstance(number, bool)
        ):
            name += f" [errno {number}]"
        if name not in names:
            names.append(name)
        # requests wraps urllib3's errors in ``args``; urllib3 keeps the next
        # one in ``reason`` or in ``args`` too.
        nested = (
            current.__cause__,
            None if current.__suppress_context__ else current.__context__,
            getattr(current, "reason", None),
            *current.args,
        )
        pending.extend(x for x in nested if isinstance(x, BaseException))
    return " <- ".join(names)
