"""MCP Apps views (SEP-1865, extension ``io.modelcontextprotocol/ui``).

An MCP App is two ordinary MCP objects: a tool, and an HTML resource under
``ui://`` that the tool names in ``_meta.ui.resourceUri``. A host that supports
the extension renders the HTML in a sandboxed frame and hands it the tool's
result; any other host ignores the metadata and gets the same result as text.
So a view needs no separate fallback tool: it draws what the model reads.

Off by default (``--apps on``, ``ServerConfig.apps``). With it off nothing here
is registered, and the tool list, the resource list and
``docs/contract.json`` are unchanged.

The parts, each usable on its own in a server that imports this package
(``docs/apps.md`` has a worked example):

- ``bridge.js``: ``McpApp``, the view side of the protocol (JSON-RPC over
  ``postMessage``) with theme, sizing and tool calls. No SDK, no CDN.
- ``base.css``: theme tokens bound to the host's style variables, and the
  table, chip, badge and button styles.
- ``compose_view()``: wraps a fragment (markup and a script that uses
  ``McpApp``) into one self-contained document with both inlined, so it runs
  under a host's default content security policy.
- ``add_app()``: registers a function as a tool and its view as the ``ui://``
  resource the tool names.
- ``view_problems()``: the checks this package's own views must pass (loads
  nothing, contacts nothing, never writes text as markup).

One built-in view, read-only, registered by ``register_apps()``:

- ``review_update_set`` + ``ui://servicenow/update-set-review.html``: an update
  set's header and its customer updates as a table the user can filter.
"""

import html
import logging
import re
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Callable, Dict, List, Optional, Set

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field
from typing_extensions import TypedDict

from servicenow_mcp.server import get_config, make_sn_request
from servicenow_mcp.tools.annotations import READ
from servicenow_mcp.tools.results import Row
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows

logger = logging.getLogger(__name__)

__all__ = [
    "REVIEW_TOOL",
    "UPDATE_SET_REVIEW_URI",
    "add_app",
    "asset",
    "compose_view",
    "register_apps",
    "review_update_set",
    "update_set_review_view",
    "view_problems",
]

UPDATE_SET_REVIEW_URI = "ui://servicenow/update-set-review.html"
REVIEW_TOOL = "review_update_set"


# ---------------------------------------------------------------------------
# Reusable parts
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def asset(name: str) -> str:
    """The text of a file shipped in this package: ``bridge.js``, ``base.css`` or a view fragment."""
    return files("servicenow_mcp.apps").joinpath(name).read_text(encoding="utf-8")


def compose_view(fragment: str, *, title: str) -> str:
    """Wrap a view fragment into one self-contained MCP Apps document.

    ``fragment`` is body content: markup, optional ``<style>``, and a
    ``<script>`` that calls ``McpApp.connect(...)``. The result inlines
    ``base.css`` in the head and ``bridge.js`` ahead of the fragment, and loads
    nothing else, so a host's default policy for a view (inline script and
    style only, no network) is enough.
    """
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{asset('base.css')}</style>\n</head>\n<body>\n"
        f"<script>\n{asset('bridge.js')}</script>\n"
        f"{fragment}\n</body>\n</html>\n"
    )


# What a self-contained, text-safe view must not contain. A view that needs the
# network declares the origins in AppConfig(csp=...) instead and skips this check.
_VIEW_RULES = (
    (
        re.compile(r"https?://|(?<![\w.])//[\w-]+\.", re.I),
        "names a URL: a view loads nothing",
    ),
    (
        re.compile(r"@import|\bsrc\s*=|\bhref\s*=", re.I),
        "loads a file (@import, src=, href=)",
    ),
    (
        re.compile(
            r"\bfetch\s*\(|XMLHttpRequest|\bWebSocket\b|\bEventSource\b|sendBeacon"
        ),
        "opens a network connection",
    ),
    (
        re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write"),
        "writes text as markup: use McpApp.el / textContent",
    ),
    (
        re.compile(r"\beval\s*\(|new\s+Function\b"),
        "evaluates a string as code",
    ),
)


def view_problems(document: str) -> List[str]:
    """Why ``document`` is not a self-contained, text-safe view; empty when it is.

    The built-in views must pass. It reads the text, it does not run it: a
    check for careless mistakes, not a sandbox (the host's frame is that).
    """
    problems = []
    for pattern, reason in _VIEW_RULES:
        match = pattern.search(document)
        if match:
            line = document.count("\n", 0, match.start()) + 1
            problems.append(f"line {line}: {reason} ({match.group(0).strip()!r})")
    return problems


def _mounted_uri(uri: str, namespace: Optional[str]) -> str:
    """``uri`` as a parent serves it after ``parent.mount(server, namespace=namespace)``."""
    if not namespace:
        return uri
    scheme, _, path = uri.partition("://")
    return f"{scheme}://{namespace}/{path}"


def _name_tool(view: str, tool_name: str) -> str:
    """Write the tool's name into the head of ``view``, where ``McpApp`` reads it.

    A host may tell a view which tool opened it (``hostContext.toolInfo``) and
    need not, and the view's script is static text. So the name the server
    knows goes into the document it serves; the host's wins when it gives one.
    A document without a plain ``<head>`` tag is served as it is.
    """
    before, head, after = view.partition("<head>")
    if not head:
        return view
    name = html.escape(tool_name, quote=True)
    return f'{before}{head}\n<meta name="mcp-app-tool" content="{name}">{after}'


def add_app(
    server: FastMCP,
    fn: Callable[..., Any],
    *,
    uri: str,
    view: str,
    namespace: Optional[str] = None,
    name: Optional[str] = None,
    view_description: Optional[str] = None,
    tags: Optional[Set[str]] = None,
    annotations: Optional[Dict[str, Any]] = None,
    prefers_border: bool = True,
) -> None:
    """Register ``fn`` as a tool whose result ``view`` renders.

    ``view`` is a complete HTML document (``compose_view()`` builds one) served
    at ``uri``, which must use the ``ui://`` scheme; the tool names it in
    ``_meta.ui.resourceUri``. The tool is an ordinary tool: its description is
    ``fn``'s docstring, it is visible to the model and to the view, and on this
    package's server the audit log, the policy checks and read-only mode apply
    to it like any other. ``annotations`` defaults to the read-only set, so
    pass the right one for a tool that writes, and tag it ``write``.

    The view is served with the tool's name in its head (``_name_tool``), so
    ``app.callTool()`` works in a host that does not say which tool opened it.

    Pass ``namespace`` when ``server`` will be mounted under one
    (``parent.mount(server, namespace="snow")``), and only then. The mount
    serves the view at ``ui://snow/...`` and renames the tool to ``snow_...``,
    but FastMCP copies the tool's ``_meta`` as it is and never sees inside the
    view, so both have to carry the mounted names from the start. Such a
    server is for mounting: served on its own, its tool names a view that is
    not there.
    """
    if not uri.startswith("ui://"):
        raise ValueError("an MCP Apps view is served under the ui:// scheme")
    tool_name = name or fn.__name__
    all_tags = set(tags or ()) | {"app"}

    mounted_name = f"{namespace}_{tool_name}" if namespace else tool_name
    document = _name_tool(view, mounted_name)

    def read_view() -> str:
        return document

    server.resource(
        uri,
        name=f"{tool_name}-view",
        description=view_description
        or f"MCP Apps view for {tool_name}. Rendered by hosts that support MCP Apps.",
        tags=all_tags,
        app=AppConfig(prefers_border=prefers_border),
    )(read_view)

    server.tool(
        name=tool_name,
        tags=all_tags,
        annotations=READ if annotations is None else annotations,
        app=AppConfig(resource_uri=_mounted_uri(uri, namespace)),
    )(fn)


# ---------------------------------------------------------------------------
# Built-in view: review_update_set
# ---------------------------------------------------------------------------

# ``application.name`` dot-walks to the scope's name: stored values keep the
# dates in UTC, like list_update_set_changes, and still give a readable scope.
_HEADER_FIELDS = (
    "sys_id,name,state,description,application.name,"
    "sys_created_by,sys_created_on,sys_updated_on"
)
_CHANGE_FIELDS = "sys_id,name,type,target_name,action,sys_created_by,sys_updated_on"


class UpdateSetReview(TypedDict):
    update_set: Row
    count: int
    limit: int
    changes: List[Row]


def update_set_review_view() -> str:
    """The complete document served at ``UPDATE_SET_REVIEW_URI``."""
    return compose_view(asset("update_set_review.html"), title="Update set review")


def review_update_set(
    update_set_sys_id: Annotated[
        str,
        Field(
            description="The sys_id of the update set",
            pattern=r"^[A-Za-z0-9_]+$",
        ),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=200, description="Maximum number of changes to return"),
    ] = 100,
) -> UpdateSetReview:
    """Review one update set: its name, state and scope, and its customer updates
    (type, target, action, author), newest first. Read-only. Clients that support
    MCP Apps also show the result as a table the user can filter."""
    config = get_config()

    header_url = build_url(config.api_url, "table", "sys_update_set", update_set_sys_id)
    header_response = make_sn_request(
        "GET", header_url, config.timeout, params={"sysparm_fields": _HEADER_FIELDS}
    )
    header = parse_json_response(header_response, header_url).get("result", {})

    changes_url = build_url(config.api_url, "table", "sys_update_xml")
    params: Dict[str, Any] = {
        "sysparm_query": f"update_set={update_set_sys_id}^ORDERBYDESCsys_updated_on",
        "sysparm_fields": _CHANGE_FIELDS,
        "sysparm_limit": limit,
    }
    changes_response = make_sn_request(
        "GET", changes_url, config.timeout, params=params
    )
    changes = result_rows(parse_json_response(changes_response, changes_url))

    return {
        "update_set": header if isinstance(header, dict) else {},
        "count": len(changes),
        "limit": limit,
        "changes": changes,
    }


def register_apps(server: FastMCP, *, namespace: Optional[str] = None) -> None:
    """Register the built-in views and their tools on ``server`` (the CLI passes the singleton).

    ``namespace`` is the one ``server`` will be mounted under, if any: see ``add_app()``.
    """
    add_app(
        server,
        review_update_set,
        name=REVIEW_TOOL,
        uri=UPDATE_SET_REVIEW_URI,
        namespace=namespace,
        view=update_set_review_view(),
        view_description=(
            "MCP Apps view for review_update_set: a filterable table of an "
            "update set's changes. Rendered by hosts that support MCP Apps."
        ),
        tags={"read", "updateset"},
    )
