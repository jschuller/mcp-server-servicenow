"""``mcp-server-servicenow --check``: a read-only connection diagnostic.

Prints one line per check to stdout and exits 0 when authentication and a
Table API read work, 1 otherwise. Every request is a GET. Output names the
instance, the auth type and the identity, never a password, secret, key or
token, so it can be pasted into a support question as is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from servicenow_mcp.utils.config import AuthType, ServerConfig
from servicenow_mcp.utils.http import build_url, parse_json_response
from servicenow_mcp.utils.user import fetch_current_user, fetch_direct_roles, has_role

OK, WARN, FAIL, INFO = "ok", "warn", "FAIL", "info"

# A base-platform table that itil and snc_read_only identities can both read, so the
# Table, record, schema and Stats probes work without any application plugin.
PROBE_TABLE = "sys_user_group"

# Prefixes of http.py's messages for a request that never reached a working
# ServiceNow API (DNS, TLS, refused connection, timeout, a hibernating PDI).
_UNREACHABLE = (
    "Cannot resolve",
    "TLS certificate",
    "Cannot connect",
    "Retry after token refresh failed",
    "Got HTML",
    "Empty response",
)


@dataclass
class Check:
    """One line of ``--check`` output."""

    status: str
    name: str
    detail: str

    def __str__(self) -> str:
        return f"{self.status:<4} {self.name:<10} {self.detail}"


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return (text[0] if text else type(exc).__name__)[:300]


def _is_unreachable(exc: BaseException) -> bool:
    message = str(exc)
    if any(marker in message for marker in _UNREACHABLE) or "timed out" in message:
        return True
    # A token request that never got an answer (requests raises these directly).
    return type(exc).__module__.startswith(("requests", "urllib3"))


def describe_config(config: ServerConfig) -> str:
    """Instance, auth and flags, with no credential values."""
    auth = config.auth
    if auth.type == AuthType.API_KEY and auth.api_key is not None:
        how = f"api_key (header {auth.api_key.header_name})"
    elif auth.type == AuthType.OAUTH and auth.oauth is not None:
        how = f"oauth, {auth.oauth.grant_type} grant, client {auth.oauth.client_id}"
        if auth.oauth.grant_type == "password":
            how += f", user {auth.oauth.username}"
    elif auth.basic is not None:
        how = f"basic, user {auth.basic.username}"
    else:
        how = auth.type.value
    flags = [
        name
        for name, on in (
            ("--read-only", config.read_only),
            ("--allow-js-queries", config.allow_js_queries),
            ("--skills off", not config.skills),
        )
        if on
    ]
    return (
        f"{config.instance_url} · auth {how} · flags: {' '.join(flags) or 'none'}"
        f" · timeout {config.timeout}s"
    )


class Doctor:
    """Runs the checks in order; later checks need the earlier ones."""

    def __init__(
        self, config: ServerConfig, request: Optional[Callable[..., Any]] = None
    ) -> None:
        self.config = config
        self._request = request
        self.checks: List[Check] = []
        self.sample_sys_id: Optional[str] = None

    def add(self, status: str, name: str, detail: str) -> None:
        self.checks.append(Check(status, name, detail))

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        request = self._request
        if request is None:
            from servicenow_mcp.server import make_sn_request

            request = make_sn_request
        response = request("GET", url, self.config.timeout, params=params)
        return parse_json_response(response, url)

    def run(self) -> int:
        self.add(INFO, "config", describe_config(self.config))
        if not self.check_identity():
            return 1
        self.check_roles()
        read_ok = self.check_table_read()
        self.check_record()
        self.check_schema()
        self.check_aggregate()
        return 0 if read_ok else 1

    def check_identity(self) -> bool:
        api = self.config.api_url
        try:
            user = fetch_current_user(api, self.config.timeout, with_roles=False)
        except Exception as exc:
            if _is_unreachable(exc):
                self.add(FAIL, "reach", _first_line(exc))
            else:
                self.add(OK, "reach", "the instance answered")
                self.add(FAIL, "auth", _first_line(exc))
            return False
        self.add(OK, "reach", "the instance answered with JSON")
        if not user:
            self.add(
                WARN,
                "identity",
                "authenticated, but the caller cannot read its own sys_user row",
            )
            return True
        self.add(
            OK,
            "identity",
            f"{user.get('user_name')} ({user.get('user_display_name') or 'no name'})",
        )
        return True

    def check_roles(self) -> None:
        api, timeout = self.config.api_url, self.config.timeout
        roles = fetch_direct_roles(api, timeout)
        if roles is None:
            self.add(
                WARN,
                "roles",
                "cannot read its own sys_user_has_role rows: write tools stay "
                "listed; add --read-only if this identity must not write",
            )
            return
        self.add(OK, "roles", f"{', '.join(roles) or 'none'} (direct grants)")
        if self.config.read_only:
            self.add(OK, "writes", "write tools hidden (--read-only)")
        elif has_role(api, timeout, "snc_read_only"):
            self.add(OK, "writes", "snc_read_only: write tools hidden")
        else:
            self.add(
                INFO, "writes", "write tools listed; your client asks before writes"
            )

    def check_table_read(self) -> bool:
        url = build_url(self.config.api_url, "table", PROBE_TABLE)
        try:
            rows = self.get(url, {"sysparm_limit": 1, "sysparm_fields": "sys_id"})
        except Exception as exc:
            self.add(FAIL, "table", f"{PROBE_TABLE} read failed: {_first_line(exc)}")
            return False
        result = rows.get("result") or []
        if result:
            self.sample_sys_id = result[0].get("sys_id")
            self.add(OK, "table", f"Table API read works ({PROBE_TABLE}, 1 row)")
        else:
            self.add(
                WARN,
                "table",
                f"Table API read works, but no {PROBE_TABLE} row is visible "
                "(none exist, or ACLs hide them from this identity)",
            )
        return True

    def check_record(self) -> None:
        """A per-record GET: get_record, get_ci and the update-set reads use it."""
        if not self.sample_sys_id:
            return
        url = build_url(self.config.api_url, "table", PROBE_TABLE, self.sample_sys_id)
        try:
            self.get(url, {"sysparm_fields": "sys_id"})
        except Exception as exc:
            self.add(
                WARN,
                "record",
                self._limit_message(
                    "Table API", "/now/table/{tableName}/{sys_id}", exc
                ),
            )
            return
        self.add(OK, "record", "single-record read works (get_record)")

    def check_schema(self) -> None:
        url = build_url(self.config.api_url, "table", "sys_dictionary")
        try:
            self.get(url, {"sysparm_query": f"name={PROBE_TABLE}", "sysparm_limit": 1})
        except Exception as exc:
            if "403" in str(exc):
                self.add(
                    WARN,
                    "schema",
                    "sys_dictionary refused (403): get_table_schema and "
                    "servicenow://schema need the personalize_dictionary role",
                )
            else:
                self.add(WARN, "schema", _first_line(exc))
            return
        self.add(OK, "schema", "sys_dictionary readable (get_table_schema works)")

    def check_aggregate(self) -> None:
        url = build_url(self.config.api_url, "stats", PROBE_TABLE)
        try:
            self.get(url, {"sysparm_count": "true"})
        except Exception as exc:
            self.add(
                WARN,
                "aggregate",
                self._limit_message("Aggregate API", "/now/stats/{tableName}", exc),
            )
            return
        self.add(
            OK,
            "aggregate",
            "Aggregate API answers (aggregate_records; results still follow table ACLs)",
        )

    def _limit_message(self, api: str, resource: str, exc: BaseException) -> str:
        message = str(exc)
        if self.config.auth.type == AuthType.API_KEY and "401" in message:
            return (
                f"{api} {resource} refused the API key (401): an access-policy "
                f"limit, not a fault. To use it, add a REST API access policy for "
                f"that API and resource with the key's auth profile"
            )
        if "403" in message:
            return f"{api} refused (403): the identity lacks a role or an ACL"
        return f"{api}: {_first_line(exc)}"


def _header() -> None:
    from servicenow_mcp import __version__

    print(f"mcp-server-servicenow {__version__} --check")


def report_config_error(message: str) -> int:
    """Print a configuration failure in the ``--check`` format."""
    _header()
    print(Check(FAIL, "config", message))
    print("result: FAILED")
    return 1


def run_doctor(config: ServerConfig) -> int:
    """Print every check and return the exit code."""
    _header()
    doctor = Doctor(config)
    code = doctor.run()
    for check in doctor.checks:
        print(check)
    print("result: " + ("OK (auth and a read work)" if code == 0 else "FAILED"))
    return code
