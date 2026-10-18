"""Tests for the CLI entry point: arg parsing, auth wiring, fail-closed startup."""

import argparse
from unittest.mock import patch

import pytest

from servicenow_mcp import cli
from tests.inventory import READ_TOOLS

# Env vars that parse_args() reads — cleared per-test so the host machine's
# environment (or a local .env) can't leak into assertions.
_CLI_ENV_VARS = [
    "SERVICENOW_INSTANCE_URL",
    "SERVICENOW_AUTH_TYPE",
    "SERVICENOW_USERNAME",
    "SERVICENOW_PASSWORD",
    "SERVICENOW_CLIENT_ID",
    "SERVICENOW_CLIENT_SECRET",
    "SERVICENOW_TOKEN_URL",
    "SERVICENOW_API_KEY",
    "SERVICENOW_API_KEY_HEADER",
    "SERVICENOW_TIMEOUT",
    "SERVICENOW_DEBUG",
    "MCP_TRANSPORT",
    "MCP_HOST",
    "PORT",
    "MCP_OAUTH_CLIENT_ID",
    "MCP_OAUTH_CLIENT_SECRET",
    "MCP_BASE_URL",
    "MCP_STATIC_TOKENS",
    "SERVICENOW_READ_ONLY",
    "SERVICENOW_ALLOW_JS_QUERIES",
    "SERVICENOW_AUDIT_LOG",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in _CLI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # main() calls load_dotenv(); keep a local .env from polluting tests
    monkeypatch.setattr(cli, "load_dotenv", lambda: None, raising=False)


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "mcp_static_tokens": None,
        "mcp_oauth_client_id": None,
        "mcp_oauth_client_secret": None,
        "mcp_base_url": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestParseArgs:
    def test_host_defaults_to_loopback(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mcp-server-servicenow"])
        args = cli.parse_args()
        assert args.host == "127.0.0.1"

    def test_host_env_override(self, monkeypatch):
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.setattr("sys.argv", ["mcp-server-servicenow"])
        args = cli.parse_args()
        assert args.host == "0.0.0.0"

    def test_transport_defaults_to_stdio(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mcp-server-servicenow"])
        args = cli.parse_args()
        assert args.transport == "stdio"


class TestParseStaticTokens:
    def test_none_when_unset(self):
        assert cli._parse_static_tokens(_args()) is None

    def test_none_when_empty(self):
        assert cli._parse_static_tokens(_args(mcp_static_tokens="")) is None

    def test_none_when_only_separators(self):
        assert cli._parse_static_tokens(_args(mcp_static_tokens=" , ,")) is None

    def test_single_token(self):
        tokens = cli._parse_static_tokens(_args(mcp_static_tokens="secret-a"))
        assert tokens == {
            "secret-a": {
                "client_id": "static-client-1",
                "scopes": [],
                "sn_auth": "service-account",
            }
        }

    def test_multiple_tokens_strip_whitespace(self):
        tokens = cli._parse_static_tokens(
            _args(mcp_static_tokens=" secret-a , secret-b ")
        )
        assert set(tokens) == {"secret-a", "secret-b"}
        assert tokens["secret-b"]["client_id"] == "static-client-2"

    def test_named_tokens_keep_their_name_when_reordered(self):
        first = cli._parse_static_tokens(_args(mcp_static_tokens="ci:tok-a,dev:tok-b"))
        second = cli._parse_static_tokens(_args(mcp_static_tokens="dev:tok-b,ci:tok-a"))
        assert first == second
        assert first["tok-a"]["client_id"] == "ci"
        assert first["tok-b"]["client_id"] == "dev"

    def test_named_and_unnamed_tokens_mix(self):
        tokens = cli._parse_static_tokens(_args(mcp_static_tokens="ci:tok-a,tok-b"))
        assert tokens["tok-a"]["client_id"] == "ci"
        assert tokens["tok-b"]["client_id"] == "static-client-2"

    @pytest.mark.parametrize("entry", ["bad name:tok", ":tok", "-ci:tok"])
    def test_entry_without_a_valid_name_is_one_whole_token(self, entry):
        tokens = cli._parse_static_tokens(_args(mcp_static_tokens=entry))
        assert tokens == {
            entry: {
                "client_id": "static-client-1",
                "scopes": [],
                "sn_auth": "service-account",
            }
        }

    def test_a_name_without_a_token_is_refused(self):
        with pytest.raises(ValueError, match="entry 1 has a name but no token"):
            cli._parse_static_tokens(_args(mcp_static_tokens="ci:"))

    def test_a_token_with_a_stray_colon_is_never_echoed(self, caplog):
        token = "a" * 64
        with caplog.at_level("WARNING"):
            tokens = cli._parse_static_tokens(_args(mcp_static_tokens=token + ":"))
        # 64 characters can't be a name, so the whole entry is the token.
        assert list(tokens) == [token + ":"]
        assert "entry 1 contains ':'" in caplog.text
        assert token not in caplog.text

    def test_spaces_around_the_colon_are_ignored(self):
        tokens = cli._parse_static_tokens(_args(mcp_static_tokens=" ci : tok-a "))
        assert tokens == {
            "tok-a": {"client_id": "ci", "scopes": [], "sn_auth": "service-account"}
        }

    def test_duplicate_name_is_refused(self):
        with pytest.raises(ValueError, match="entry 2 repeats a name"):
            cli._parse_static_tokens(_args(mcp_static_tokens="ci:tok-a,ci:tok-b"))

    def test_duplicate_token_is_refused_without_echoing_it(self):
        with pytest.raises(ValueError) as exc_info:
            cli._parse_static_tokens(_args(mcp_static_tokens="ci:tok-a,dev:tok-a"))
        assert "tok-a" not in str(exc_info.value)

    def test_short_token_warns_with_name_and_length_only(self, caplog):
        with caplog.at_level("WARNING"):
            cli._parse_static_tokens(_args(mcp_static_tokens="ci:short-token"))
        assert "static token ci is 11 characters; use at least 32" in caplog.text
        assert "short-token" not in caplog.text

    def test_long_token_does_not_warn(self, caplog):
        with caplog.at_level("WARNING"):
            cli._parse_static_tokens(_args(mcp_static_tokens="ci:" + "a" * 32))
        assert "static token" not in caplog.text


class TestHasMcpOauth:
    def test_false_when_nothing_set(self):
        assert cli._has_mcp_oauth(_args()) is False

    @pytest.mark.parametrize(
        "missing",
        ["mcp_oauth_client_id", "mcp_oauth_client_secret", "mcp_base_url"],
    )
    def test_false_when_any_piece_missing(self, missing):
        kwargs = {
            "mcp_oauth_client_id": "id",
            "mcp_oauth_client_secret": "secret",
            "mcp_base_url": "https://example.com",
        }
        kwargs[missing] = None
        assert cli._has_mcp_oauth(_args(**kwargs)) is False

    def test_true_when_all_present(self):
        assert (
            cli._has_mcp_oauth(
                _args(
                    mcp_oauth_client_id="id",
                    mcp_oauth_client_secret="secret",
                    mcp_base_url="https://example.com",
                )
            )
            is True
        )


_BASIC_ARGV = [
    "mcp-server-servicenow",
    "--instance-url",
    "https://test.service-now.com",
    "--auth-type",
    "basic",
    "--username",
    "admin",
    "--password",
    "secret",
]


class TestFailClosed:
    """A non-stdio listener must never start without MCP endpoint auth."""

    def test_http_without_mcp_auth_exits(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv", [*_BASIC_ARGV, "--transport", "streamable-http"]
        )
        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 1
        mock_run.assert_not_called()
        assert "refusing to start" in capsys.readouterr().err

    def test_stdio_without_mcp_auth_is_allowed(self, monkeypatch):
        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            cli.main()
        mock_run.assert_called_once_with(transport="stdio")

    def test_http_with_static_tokens_starts_listener(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                *_BASIC_ARGV,
                "--transport",
                "streamable-http",
                "--mcp-static-tokens",
                "tok-1,tok-2",
            ],
        )
        from servicenow_mcp.server import mcp

        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            cli.main()
        mock_run.assert_called_once_with(
            transport="streamable-http", host="127.0.0.1", port=8080
        )
        # Static tokens compose into MultiAuth on the server
        assert mcp.auth is not None
        assert type(mcp.auth).__name__ == "MultiAuth"

    def test_http_writes_warn_about_the_shared_identity(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "sys.argv",
            [
                *_BASIC_ARGV,
                "--transport",
                "streamable-http",
                "--mcp-static-tokens",
                "tok-1",
            ],
        )
        with patch("servicenow_mcp.server.mcp.run"), caplog.at_level("WARNING"):
            cli.main()
        assert "write tools are enabled over HTTP" in caplog.text
        assert (
            "all 1 static token(s) write as the one configured service account"
            in caplog.text
        )

    def test_http_read_only_does_not_warn_about_writes(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "sys.argv",
            [
                *_BASIC_ARGV,
                "--transport",
                "streamable-http",
                "--mcp-static-tokens",
                "tok-1",
                "--read-only",
            ],
        )
        with patch("servicenow_mcp.server.mcp.run"), caplog.at_level("WARNING"):
            cli.main()
        assert "write tools are enabled" not in caplog.text

    def test_startup_turns_off_fastmcp_update_check(self, monkeypatch):
        import fastmcp

        monkeypatch.setattr(fastmcp.settings, "check_for_updates", "stable")
        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        with patch("servicenow_mcp.server.mcp.run"):
            cli.main()
        assert fastmcp.settings.check_for_updates == "off"

    def test_stdio_does_not_warn_about_writes(self, monkeypatch, caplog):
        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        with patch("servicenow_mcp.server.mcp.run"), caplog.at_level("WARNING"):
            cli.main()
        assert "write tools are enabled" not in caplog.text

    def test_http_with_oauth_proxy_starts_listener(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                "mcp-server-servicenow",
                "--instance-url",
                "https://test.service-now.com",
                "--transport",
                "streamable-http",
                "--host",
                "0.0.0.0",
                "--port",
                "9090",
                "--mcp-oauth-client-id",
                "cid",
                "--mcp-oauth-client-secret",
                "csecret",
                "--mcp-base-url",
                "https://mcp.example.com",
            ],
        )
        from servicenow_mcp.server import mcp

        with (
            patch(
                "servicenow_mcp.auth.sn_oauth_provider.ServiceNowProvider"
            ) as mock_provider,
            patch("servicenow_mcp.server.mcp.run") as mock_run,
        ):
            cli.main()
        mock_provider.assert_called_once_with(
            instance_url="https://test.service-now.com",
            client_id="cid",
            client_secret="csecret",
            base_url="https://mcp.example.com",
        )
        mock_run.assert_called_once_with(
            transport="streamable-http", host="0.0.0.0", port=9090
        )
        assert mcp.auth is mock_provider.return_value

    def test_missing_instance_url_exits(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mcp-server-servicenow"])
        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 1
        mock_run.assert_not_called()


class TestSafetyFlags:
    def test_flags_parse_into_config(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                *_BASIC_ARGV,
                "--read-only",
                "--allow-js-queries",
                "--audit-log",
                "off",
            ],
        )
        config = cli.create_config(cli.parse_args())
        assert config.read_only is True
        assert config.allow_js_queries is True
        assert config.audit_log == "off"

    def test_defaults(self, monkeypatch):
        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        config = cli.create_config(cli.parse_args())
        assert config.read_only is False
        assert config.allow_js_queries is False
        assert config.audit_log == "stderr"

    def test_env_vars(self, monkeypatch):
        monkeypatch.setenv("SERVICENOW_READ_ONLY", "true")
        monkeypatch.setenv("SERVICENOW_AUDIT_LOG", "/tmp/audit.jsonl")
        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        config = cli.create_config(cli.parse_args())
        assert config.read_only is True
        assert config.audit_log == "/tmp/audit.jsonl"

    @pytest.mark.parametrize("flag", ["--table-allowlist", "--table-denylist"])
    def test_removed_table_list_flags_fail(self, monkeypatch, flag):
        """0.8.0 removed the table lists; argparse refuses the old flags."""
        monkeypatch.setattr("sys.argv", [*_BASIC_ARGV, flag, "sys_user*"])
        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args()
        assert exc_info.value.code == 2

    def test_unexpanded_plugin_placeholders_are_ignored(self, monkeypatch):
        """Claude Code passes unset plugin env vars through as literal ${VAR}."""
        monkeypatch.setenv("SERVICENOW_TIMEOUT", "${SERVICENOW_TIMEOUT}")
        monkeypatch.setenv("SERVICENOW_READ_ONLY", "${SERVICENOW_READ_ONLY}")
        monkeypatch.setenv("SERVICENOW_AUDIT_LOG", "${SERVICENOW_AUDIT_LOG}")
        monkeypatch.setenv("SERVICENOW_TOKEN_URL", "")
        monkeypatch.setenv("SERVICENOW_API_KEY_HEADER", "${SERVICENOW_API_KEY_HEADER}")
        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        args = cli.parse_args()
        assert args.timeout == 30
        assert args.read_only is False
        assert args.audit_log == "stderr"
        assert args.token_url is None
        assert args.api_key_header == "x-sn-apikey"

    def test_read_only_hides_write_tools(self, monkeypatch):
        import asyncio

        from fastmcp import Client

        from servicenow_mcp.server import mcp

        monkeypatch.setattr("sys.argv", [*_BASIC_ARGV, "--read-only"])
        with patch("servicenow_mcp.server.mcp.run"):
            cli.main()

        async def count():
            async with Client(mcp) as client:
                return len(await client.list_tools())

        assert asyncio.run(count()) == len(READ_TOOLS)

    def test_server_instructions_on_wire(self, monkeypatch):
        """The model-facing instructions name the skill resources (SEP-2640 pattern)."""
        import asyncio

        from fastmcp import Client

        from servicenow_mcp.server import SERVER_INSTRUCTIONS, mcp

        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        with patch("servicenow_mcp.server.mcp.run"):
            cli.main()

        async def instructions():
            async with Client(mcp) as client:
                return client.instructions

        wire = asyncio.run(instructions())
        assert wire == SERVER_INSTRUCTIONS
        assert "skill://analyzing-access/SKILL.md" in wire
        assert "servicenow://help/query-syntax" in wire

    def test_audit_log_configured(self, monkeypatch):
        from servicenow_mcp.middleware import audit

        monkeypatch.setattr("sys.argv", list(_BASIC_ARGV))
        with patch("servicenow_mcp.server.mcp.run"):
            cli.main()
        assert audit.is_enabled() is True
        monkeypatch.setattr("sys.argv", [*_BASIC_ARGV, "--audit-log", "off"])
        with patch("servicenow_mcp.server.mcp.run"):
            cli.main()
        assert audit.is_enabled() is False


class TestInstanceUrl:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://dev1.service-now.com",
            "https://dev1.service-now.com/",
            "  https://dev1.service-now.com  ",
            "dev1.service-now.com",
            "dev1",
            "https://dev1.service-now.com/now/nav/ui/home?x=1#frag",
            "HTTPS://Dev1.Service-Now.com/",
        ],
    )
    def test_pasted_forms_normalise(self, raw):
        assert cli.normalize_instance_url(raw) == "https://dev1.service-now.com"

    def test_explicit_scheme_and_port_are_kept(self):
        assert cli.normalize_instance_url("http://localhost:8080/x") == (
            "http://localhost:8080"
        )

    def test_no_host_is_an_error(self):
        with pytest.raises(ValueError, match="Invalid ServiceNow instance URL"):
            cli.normalize_instance_url("https://")

    def test_config_and_token_url_use_the_normalised_url(self, monkeypatch, caplog):
        monkeypatch.setattr(
            "sys.argv",
            [*_OAUTH_ARGV[:2], "dev1/now/nav/ui/home", *_OAUTH_ARGV[3:]],
        )
        with caplog.at_level("INFO"):
            config = cli.create_config(cli.parse_args())
        assert config.instance_url == "https://dev1.service-now.com"
        assert config.auth.oauth.token_url == (
            "https://dev1.service-now.com/oauth_token.do"
        )
        assert "normalised to https://dev1.service-now.com" in caplog.text


_OAUTH_ARGV = [
    "mcp-server-servicenow",
    "--instance-url",
    "https://test.service-now.com",
    "--auth-type",
    "oauth",
    "--client-id",
    "cid",
    "--client-secret",
    "csecret",
]


class TestOAuthGrantSelection:
    def test_no_user_credentials_selects_client_credentials(self, monkeypatch):
        monkeypatch.setattr("sys.argv", list(_OAUTH_ARGV))
        config = cli.create_config(cli.parse_args())
        assert config.auth.oauth.grant_type == "client_credentials"
        assert config.auth.oauth.token_url == (
            "https://test.service-now.com/oauth_token.do"
        )

    def test_user_credentials_select_the_password_grant(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv", [*_OAUTH_ARGV, "--username", "svc", "--password", "pw"]
        )
        config = cli.create_config(cli.parse_args())
        assert config.auth.oauth.grant_type == "password"

    @pytest.mark.parametrize("half", [["--username", "svc"], ["--password", "pw"]])
    def test_half_set_user_credentials_are_an_error(self, monkeypatch, half):
        monkeypatch.setattr("sys.argv", [*_OAUTH_ARGV, *half])
        with pytest.raises(
            ValueError, match="SERVICENOW_USERNAME and SERVICENOW_PASSWORD"
        ):
            cli.create_config(cli.parse_args())

    def test_client_secret_still_required(self, monkeypatch):
        monkeypatch.setattr("sys.argv", _OAUTH_ARGV[:-2])
        with pytest.raises(ValueError, match="client-id and client-secret"):
            cli.create_config(cli.parse_args())

    def test_startup_log_names_the_grant(self, monkeypatch, caplog):
        monkeypatch.setattr("sys.argv", list(_OAUTH_ARGV))
        with patch("servicenow_mcp.server.mcp.run"), caplog.at_level("INFO"):
            cli.main()
        assert "OAuth client_credentials grant" in caplog.text


class TestStaticTokensNeedServiceAccount:
    _HTTP_STATIC = [
        "mcp-server-servicenow",
        "--instance-url",
        "https://test.service-now.com",
        "--transport",
        "streamable-http",
        "--mcp-static-tokens",
        "tok-1",
    ]

    def test_without_creds_exits_with_clear_message(self, monkeypatch, caplog):
        monkeypatch.setattr("sys.argv", list(self._HTTP_STATIC))
        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 1
        mock_run.assert_not_called()
        assert "MCP_STATIC_TOKENS requires ServiceNow service-account" in caplog.text

    def test_api_key_counts_as_service_account(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [*self._HTTP_STATIC, "--auth-type", "api_key", "--api-key", "k-1"],
        )
        from servicenow_mcp import server

        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            cli.main()
        mock_run.assert_called_once()
        assert server.get_auth_manager().config.type.value == "api_key"

    def test_oauth_proxy_plus_static_builds_auth_manager(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                *self._HTTP_STATIC,
                "--mcp-oauth-client-id",
                "cid",
                "--mcp-oauth-client-secret",
                "csecret",
                "--mcp-base-url",
                "https://mcp.example.com",
                "--username",
                "svc",
                "--password",
                "pw",
            ],
        )
        from servicenow_mcp import server

        with (
            patch("servicenow_mcp.auth.sn_oauth_provider.ServiceNowProvider"),
            patch("servicenow_mcp.server.mcp.run") as mock_run,
        ):
            cli.main()
        mock_run.assert_called_once()
        assert server.get_auth_manager().config.basic.username == "svc"
        assert type(server.mcp.auth).__name__ == "MultiAuth"

    def test_oauth_proxy_plus_static_without_creds_exits(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                *self._HTTP_STATIC,
                "--mcp-oauth-client-id",
                "cid",
                "--mcp-oauth-client-secret",
                "csecret",
                "--mcp-base-url",
                "https://mcp.example.com",
            ],
        )
        with patch("servicenow_mcp.server.mcp.run") as mock_run:
            with pytest.raises(SystemExit):
                cli.main()
        mock_run.assert_not_called()
