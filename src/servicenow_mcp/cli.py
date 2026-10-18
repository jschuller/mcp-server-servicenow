"""CLI entry point for the ServiceNow MCP server."""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlsplit

from dotenv import load_dotenv

from servicenow_mcp.utils.config import (
    DEFAULT_API_KEY_HEADER,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    OAuthConfig,
    ApiKeyConfig,
    ServerConfig,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read an env var, treating empty strings and unexpanded ``${VAR}`` as unset.

    Claude Code passes plugin env vars through verbatim when they are not set
    on the host (``"${SERVICENOW_TIMEOUT}"``), so the literal must not reach
    ``int()`` or a file path.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    if not value or (value.startswith("${") and value.endswith("}")):
        return default
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name)
    if value is None:
        return default
    return value.lower() in _TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    value = _env_str(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r; using %d", name, value, default)
        return default


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    from servicenow_mcp import __version__

    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")
    parser.add_argument(
        "--version", action="version", version=f"mcp-server-servicenow {__version__}"
    )

    parser.add_argument(
        "--instance-url",
        help="ServiceNow instance URL",
        default=_env_str("SERVICENOW_INSTANCE_URL"),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=_env_bool("SERVICENOW_DEBUG", False),
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=_env_int("SERVICENOW_TIMEOUT", 30),
    )
    parser.add_argument(
        "--auth-type",
        choices=["basic", "oauth", "api_key"],
        default=_env_str("SERVICENOW_AUTH_TYPE", "basic"),
    )
    parser.add_argument("--username", default=_env_str("SERVICENOW_USERNAME"))
    parser.add_argument("--password", default=_env_str("SERVICENOW_PASSWORD"))
    parser.add_argument("--client-id", default=_env_str("SERVICENOW_CLIENT_ID"))
    parser.add_argument("--client-secret", default=_env_str("SERVICENOW_CLIENT_SECRET"))
    parser.add_argument("--token-url", default=_env_str("SERVICENOW_TOKEN_URL"))
    parser.add_argument("--api-key", default=_env_str("SERVICENOW_API_KEY"))
    parser.add_argument(
        "--api-key-header",
        default=_env_str("SERVICENOW_API_KEY_HEADER", DEFAULT_API_KEY_HEADER),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Check the connection and identity with read-only requests, print one "
            "line per check and exit (0 when auth and a read work)"
        ),
    )
    parser.add_argument(
        "--validate-skills",
        nargs="+",
        metavar="PATH",
        help=(
            "Check skill folders (or folders above them) against the Agent Skills "
            "specification and this server's skill profile, offline; print one line "
            "per skill and exit (0 when no errors)"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="With --validate-skills: warnings fail too",
    )
    parser.add_argument(
        "--eval-mocks",
        metavar="PLUGIN_DIR",
        help=(
            "Write claude plugin eval mocks of this server's tools into PLUGIN_DIR/evals/"
            "mocks/<server>/ (tools list, default mocks, a fixture per declared table) "
            "and exit; existing mocks and fixtures are kept"
        ),
    )
    parser.add_argument(
        "--eval-summary",
        metavar="RESULT_JSON",
        help=(
            "Print a Markdown summary of a finished claude plugin eval run "
            "(aggregate-result.json) for a RESULTS.md, and exit"
        ),
    )
    parser.add_argument(
        "--baseline",
        metavar="RESULT_JSON",
        help=(
            "With --eval-summary: a tools-only run of the same cases (see "
            "--eval-baseline), to report what the skills add over the bare tools"
        ),
    )
    parser.add_argument(
        "--eval-baseline",
        nargs=2,
        metavar=("PLUGIN_DIR", "OUT_DIR"),
        help=(
            "Copy a skills plugin without its skills into OUT_DIR, so "
            "claude plugin eval OUT_DIR runs the same cases against the bare tools"
        ),
    )
    parser.add_argument(
        "--badge",
        metavar="FILE",
        help="With --eval-summary: also write a shields.io endpoint badge to FILE",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=_env_str("MCP_TRANSPORT", "stdio"),
        help="MCP transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=_env_str("MCP_HOST", "127.0.0.1"),
        help=(
            "Host to bind to for HTTP transport (default: 127.0.0.1; "
            "set 0.0.0.0 explicitly to listen on all interfaces)"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("PORT", 8080),
        help="Port for HTTP transport (default: 8080)",
    )

    # MCP endpoint OAuth (per-user SN auth via OAuth 2.1 + PKCE proxy)
    parser.add_argument(
        "--mcp-oauth-client-id",
        default=_env_str("MCP_OAUTH_CLIENT_ID"),
        help="SN OAuth app client ID (from Application Registry) for MCP endpoint auth",
    )
    parser.add_argument(
        "--mcp-oauth-client-secret",
        default=_env_str("MCP_OAUTH_CLIENT_SECRET"),
        help="SN OAuth app client secret for MCP endpoint auth",
    )
    parser.add_argument(
        "--mcp-base-url",
        default=_env_str("MCP_BASE_URL"),
        help="Public URL of this MCP server (e.g. https://my-server.run.app)",
    )
    parser.add_argument(
        "--mcp-static-tokens",
        default=_env_str("MCP_STATIC_TOKENS"),
        help=(
            "Comma-separated static bearer tokens for CI/CD auth, each `token` or "
            "`name:token` (the audit log's user; default static-client-<position>). "
            "Tokens under 32 characters log a warning. Callers share the "
            "configured ServiceNow service-account credentials (MCP_STATIC_TOKENS; "
            "prefer the variable to the flag)."
        ),
    )

    # Safety rails
    safety = parser.add_argument_group("safety rails")
    safety.add_argument(
        "--read-only",
        action="store_true",
        default=_env_bool("SERVICENOW_READ_ONLY", False),
        help="Hide write tools and refuse non-GET requests (SERVICENOW_READ_ONLY)",
    )
    safety.add_argument(
        "--allow-js-queries",
        action="store_true",
        default=_env_bool("SERVICENOW_ALLOW_JS_QUERIES", False),
        help="Permit arbitrary javascript: in caller queries (SERVICENOW_ALLOW_JS_QUERIES)",
    )
    safety.add_argument(
        "--audit-log",
        default=_env_str("SERVICENOW_AUDIT_LOG", "stderr"),
        help="Audit log target: 'stderr' (default), 'off', or a file path (SERVICENOW_AUDIT_LOG)",
    )

    args = parser.parse_args()
    modes = [
        flag
        for flag, value in (
            ("--check", args.check),
            ("--validate-skills", args.validate_skills),
            ("--eval-mocks", args.eval_mocks),
            ("--eval-summary", args.eval_summary),
            ("--eval-baseline", args.eval_baseline),
        )
        if value
    ]
    if len(modes) > 1:
        parser.error(f"{' and '.join(modes)} can't be combined; run them one at a time")
    for flag, value, parent in (
        ("--baseline", args.baseline, "--eval-summary"),
        ("--badge", args.badge, "--eval-summary"),
        ("--strict", args.strict, "--validate-skills"),
    ):
        if value and parent not in modes:
            parser.error(f"{flag} works only with {parent}")
    return args


def _safety_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "read_only": bool(getattr(args, "read_only", False)),
        "allow_js_queries": bool(getattr(args, "allow_js_queries", False)),
        "audit_log": getattr(args, "audit_log", None) or "stderr",
    }


def normalize_instance_url(raw: str) -> str:
    """Reduce what people paste to ``scheme://host[:port]``.

    Trims, adds ``https://`` when there is no scheme, expands a bare instance
    name (``dev12345``) to ``dev12345.service-now.com`` and drops any path,
    query or fragment — a URL copied from the UI (``/now/nav/ui/home``) would
    otherwise send every API call to a login page.
    """
    value = raw.strip()
    bare = "://" not in value
    if bare:
        value = f"https://{value}"
    parts = urlsplit(value)
    host = parts.hostname
    if not host:
        raise ValueError(f"Invalid ServiceNow instance URL: {raw!r}")
    if bare and "." not in host and not parts.port:
        host = f"{host}.service-now.com"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.lower()}://{host}{port}"


def create_config(
    args: argparse.Namespace, *, require_sn_creds: bool = True
) -> ServerConfig:
    """Create server configuration from parsed arguments.

    With ``require_sn_creds=False`` (OAuth-proxy mode without static tokens)
    no ServiceNow service-account credentials are needed: every request
    carries the caller's own token.
    """
    if not args.instance_url:
        raise ValueError(
            "ServiceNow instance URL is required (--instance-url or SERVICENOW_INSTANCE_URL)"
        )
    instance_url = normalize_instance_url(args.instance_url)
    if instance_url != args.instance_url.strip():
        logger.info("Instance URL normalised to %s", instance_url)

    auth_config: AuthConfig
    if not require_sn_creds:
        auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="", password="")
        )
        return ServerConfig(
            instance_url=instance_url,
            auth=auth_config,
            debug=args.debug,
            timeout=args.timeout,
            **_safety_kwargs(args),
        )

    auth_type = AuthType(args.auth_type.lower())

    if auth_type == AuthType.BASIC:
        if not args.username or not args.password:
            raise ValueError("Username and password required for basic auth")
        auth_config = AuthConfig(
            type=auth_type,
            basic=BasicAuthConfig(username=args.username, password=args.password),
        )

    elif auth_type == AuthType.OAUTH:
        if not args.client_id or not args.client_secret:
            raise ValueError("client-id and client-secret required for OAuth")
        if bool(args.username) != bool(args.password):
            raise ValueError(
                "OAuth: set both SERVICENOW_USERNAME and SERVICENOW_PASSWORD for the "
                "password grant, or neither for the client credentials grant"
            )
        token_url = args.token_url or f"{instance_url}/oauth_token.do"
        auth_config = AuthConfig(
            type=auth_type,
            oauth=OAuthConfig(
                client_id=args.client_id,
                client_secret=args.client_secret,
                username=args.username,
                password=args.password,
                token_url=token_url,
            ),
        )

    elif auth_type == AuthType.API_KEY:
        if not args.api_key:
            raise ValueError("API key required for api_key auth")
        auth_config = AuthConfig(
            type=auth_type,
            api_key=ApiKeyConfig(api_key=args.api_key, header_name=args.api_key_header),
        )

    else:
        raise ValueError(f"Unsupported auth type: {args.auth_type}")

    return ServerConfig(
        instance_url=instance_url,
        auth=auth_config,
        debug=args.debug,
        timeout=args.timeout,
        **_safety_kwargs(args),
    )


# Up to 32 characters, so a 64-hex token with a stray ':' doesn't read as a
# name. A token that contains ':' after a shorter name-like prefix would still
# split: the docs say unnamed tokens must not contain ':'.
_TOKEN_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
MIN_STATIC_TOKEN_LENGTH = 32


def _parse_static_tokens(args: argparse.Namespace) -> dict[str, dict[str, Any]] | None:
    """Parse comma-separated static bearer tokens into StaticTokenVerifier format.

    Each entry is ``token`` or ``name:token``. A name is what the audit log
    records as ``user``, so attribution survives reordering the list; unnamed
    tokens are ``static-client-<position>`` and must not contain ``:``. Returns
    None if no tokens are configured.
    ``sn_auth: service-account`` tells ``get_sn_bearer_token`` that this is an
    MCP credential, not a ServiceNow token to forward.
    """
    raw = getattr(args, "mcp_static_tokens", None)
    if not raw:
        return None
    tokens: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(raw.split(","), 1):
        entry = entry.strip()
        if not entry:
            continue
        # Messages name an entry by its position: its text may be a token.
        name, sep, token = entry.partition(":")
        name, token = name.strip(), token.strip()
        if sep and _TOKEN_NAME.match(name):
            if not token:
                raise ValueError(
                    f"MCP_STATIC_TOKENS entry {i} has a name but no token after ':'"
                )
        else:
            if sep:
                logger.warning(
                    "MCP_STATIC_TOKENS entry %d contains ':' but does not start with "
                    "a name (up to 32 letters, digits, '.', '_', '-'): the whole "
                    "entry is the token",
                    i,
                )
            name, token = f"static-client-{i}", entry
        if name in {meta["client_id"] for meta in tokens.values()}:
            raise ValueError(
                f"MCP_STATIC_TOKENS entry {i} repeats a name; names must be unique"
            )
        if token in tokens:
            raise ValueError(f"MCP_STATIC_TOKENS entry {i} repeats a token")
        if len(token) < MIN_STATIC_TOKEN_LENGTH:
            # Position and length only: even a name may be token text.
            logger.warning(
                "MCP_STATIC_TOKENS entry %d is %d characters; use at least %d "
                "(openssl rand -hex 32)",
                i,
                len(token),
                MIN_STATIC_TOKEN_LENGTH,
            )
        tokens[token] = {
            "client_id": name,
            "scopes": [],
            "sn_auth": "service-account",
        }
    return tokens or None


def _warn_writes_over_http(static_tokens: dict[str, dict[str, Any]] | None) -> None:
    """Say at startup that write tools are served over the network.

    The server does not confirm writes: the MCP client approves them, and a
    client without prompts (or a raw HTTP caller) can run them unasked. Static
    tokens make it worse, since every token holder writes as one shared
    ServiceNow identity.
    """
    shared = (
        f"; all {len(static_tokens)} static token(s) write as the one configured "
        "service account"
        if static_tokens
        else ""
    )
    logger.warning(
        "write tools are enabled over HTTP and the MCP client alone approves "
        "them%s. Use --read-only (SERVICENOW_READ_ONLY=true) or an "
        "snc_read_only identity unless callers need to write.",
        shared,
    )


def _has_mcp_oauth(args: argparse.Namespace) -> bool:
    """Check if MCP endpoint OAuth is configured."""
    return bool(
        args.mcp_oauth_client_id and args.mcp_oauth_client_secret and args.mcp_base_url
    )


def run_check(args: argparse.Namespace) -> int:
    """``--check``: diagnose the configured service account, then exit."""
    from servicenow_mcp.doctor import report_config_error, run_doctor

    # stdout carries the report; keep stderr to warnings unless --debug.
    logging.getLogger().setLevel(logging.DEBUG if args.debug else logging.WARNING)
    try:
        config = create_config(args)
    except ValueError as exc:
        return report_config_error(str(exc))

    from servicenow_mcp.server import init_services

    init_services(config)
    return run_doctor(config)


def run_validate_skills(paths: List[str], *, strict: bool) -> int:
    """``--validate-skills``: lint skills offline and print the report."""
    from servicenow_mcp import __version__
    from servicenow_mcp.skill_lint import lint_skills, render

    logging.getLogger().setLevel(logging.WARNING)
    text, code = render(lint_skills([Path(p) for p in paths]), __version__, strict)
    print(text)
    return code


def run_eval_mocks(plugin_dir: str) -> int:
    """``--eval-mocks``: write the mock kit for a skills plugin."""
    from servicenow_mcp import __version__
    from servicenow_mcp.eval_kit import EvalKitError, write_eval_mocks

    logging.getLogger().setLevel(logging.WARNING)
    try:
        done = write_eval_mocks(Path(plugin_dir), __version__)
    except EvalKitError as exc:
        print(f"error   {exc}", file=sys.stderr)
        return 1
    print(f"mcp-server-servicenow {__version__} --eval-mocks")
    for action, path in done:
        print(f"{action:<7} {path}")
    return 0


def run_eval_baseline(plugin_dir: str, out_dir: str) -> int:
    """``--eval-baseline``: write a tools-only copy of a skills plugin."""
    from servicenow_mcp.eval_kit import EvalKitError, write_tools_only

    try:
        written = write_tools_only(Path(plugin_dir), Path(out_dir))
    except EvalKitError as exc:
        print(f"error   {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote   {Path(out_dir) / path}")
    return 0


def run_eval_summary(
    result: str, badge: Optional[str], baseline: Optional[str] = None
) -> int:
    """``--eval-summary``: print a run's summary, optionally write its badge."""
    from servicenow_mcp.eval_kit import EvalKitError, summarize

    logging.getLogger().setLevel(logging.WARNING)
    try:
        text, badge_json = summarize(Path(result), Path(baseline) if baseline else None)
    except EvalKitError as exc:
        print(f"error   {exc}", file=sys.stderr)
        return 1
    if badge:
        try:
            Path(badge).write_text(json.dumps(badge_json) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"error   {badge}: cannot write the badge ({exc})", file=sys.stderr)
            return 1
    print(text)
    return 0


def main() -> None:
    """Main entry point."""
    load_dotenv()

    try:
        args = parse_args()

        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        if getattr(args, "eval_mocks", None):
            sys.exit(run_eval_mocks(args.eval_mocks))

        if getattr(args, "eval_summary", None):
            sys.exit(run_eval_summary(args.eval_summary, args.badge, args.baseline))

        if getattr(args, "eval_baseline", None):
            sys.exit(run_eval_baseline(*args.eval_baseline))

        if getattr(args, "validate_skills", None):
            sys.exit(run_validate_skills(args.validate_skills, strict=args.strict))

        if getattr(args, "check", False):
            sys.exit(run_check(args))

        # FastMCP's startup banner asks PyPI for a newer FastMCP; this server
        # makes no requests except to the instance (docs/privacy.md).
        import fastmcp

        fastmcp.settings.check_for_updates = "off"

        use_mcp_oauth = _has_mcp_oauth(args) and args.transport != "stdio"
        static_tokens = _parse_static_tokens(args)
        # Static-token callers share one ServiceNow identity, so the service
        # account is required whenever they are configured — even alongside
        # the OAuth proxy.
        require_sn_creds = (not use_mcp_oauth) or bool(static_tokens)

        try:
            config = create_config(args, require_sn_creds=require_sn_creds)
        except ValueError as exc:
            if static_tokens and "instance URL" not in str(exc):
                raise ValueError(
                    "MCP_STATIC_TOKENS requires ServiceNow service-account "
                    "credentials (SERVICENOW_USERNAME/PASSWORD, SERVICENOW_API_KEY, "
                    f"or OAuth client credentials): {exc}"
                ) from exc
            raise

        logger.info(f"Starting ServiceNow MCP server for {config.instance_url}")
        if require_sn_creds and config.auth.oauth is not None:
            logger.info("ServiceNow auth: OAuth %s grant", config.auth.oauth.grant_type)

        # Initialize services before importing tool modules
        from servicenow_mcp.server import mcp, init_services

        init_services(config, require_auth_manager=require_sn_creds)

        # Wire up MCP endpoint auth
        if use_mcp_oauth:
            from servicenow_mcp.auth.sn_oauth_provider import ServiceNowProvider

            provider = ServiceNowProvider(
                instance_url=config.instance_url,
                client_id=args.mcp_oauth_client_id,
                client_secret=args.mcp_oauth_client_secret,
                base_url=args.mcp_base_url,
            )

            if static_tokens:
                from fastmcp.server.auth import MultiAuth, StaticTokenVerifier

                static_verifier = StaticTokenVerifier(tokens=static_tokens)
                mcp.auth = MultiAuth(server=provider, verifiers=[static_verifier])
                logger.info(
                    "MCP endpoint auth: MultiAuth (OAuth 2.1 + PKCE + %d static tokens)",
                    len(static_tokens),
                )
            else:
                mcp.auth = provider
                logger.info("MCP endpoint auth: OAuth 2.1 + PKCE (per-user SN tokens)")

        elif static_tokens and args.transport != "stdio":
            from fastmcp.server.auth import MultiAuth, StaticTokenVerifier

            static_verifier = StaticTokenVerifier(tokens=static_tokens)
            mcp.auth = MultiAuth(verifiers=[static_verifier])
            logger.info(
                "MCP endpoint auth: %d static bearer tokens", len(static_tokens)
            )

        # Import tool and resource modules to trigger @mcp.tool()/@mcp.resource() registration
        import servicenow_mcp.tools.table_tools  # noqa: F401
        import servicenow_mcp.tools.cmdb_tools  # noqa: F401
        import servicenow_mcp.tools.system_tools  # noqa: F401
        import servicenow_mcp.tools.update_set_tools  # noqa: F401
        import servicenow_mcp.resources  # noqa: F401

        # Safety rails
        if config.read_only:
            mcp.disable(tags={"write"}, components={"tool"})
            logger.info("Read-only mode: write tools hidden, non-GET requests refused")
        elif args.transport != "stdio":
            _warn_writes_over_http(static_tokens)

        from servicenow_mcp.middleware.audit import configure_audit_log

        if configure_audit_log(config.audit_log, transport=args.transport):
            logger.info("Audit log: %s", config.audit_log)

        logger.info(f"Transport: {args.transport}")
        if args.transport == "stdio":
            mcp.run(transport=args.transport)
        else:
            # Fail closed: never expose a network listener without MCP auth.
            if not use_mcp_oauth and not static_tokens:
                print(
                    f"refusing to start {args.transport} listener without "
                    "authentication; configure MCP_OAUTH_* or "
                    "MCP_STATIC_TOKENS, or use --transport stdio",
                    file=sys.stderr,
                )
                sys.exit(1)
            mcp.run(transport=args.transport, host=args.host, port=args.port)

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
