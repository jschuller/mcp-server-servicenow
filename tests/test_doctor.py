"""--check: one line per check, GETs only, no secrets, exit 0 when auth + read work."""

from typing import Any, Callable, Dict
from unittest.mock import Mock, patch

import pytest

from servicenow_mcp import cli, server
from servicenow_mcp.doctor import Doctor, describe_config, run_doctor
from servicenow_mcp.utils.config import ApiKeyConfig, AuthConfig, AuthType, OAuthConfig
from servicenow_mcp.utils.http import ServiceNowAPIError
from tests.conftest import make_server_config, sn_response

SECRET = "SUPER-SECRET-VALUE"
API_KEY_AUTH = AuthConfig(type=AuthType.API_KEY, api_key=ApiKeyConfig(api_key=SECRET))

ME = {"result": [{"user_name": "svc.apikey", "name": "API key user", "sys_id": "u1"}]}
ROLES = {"result": [{"role.name": "itil"}, {"role.name": "snc_read_only"}]}
HELD = {"result": [{"sys_id": "r1"}]}
ONE_INCIDENT = {"result": [{"sys_id": "i1"}]}


def _html() -> Mock:
    response = sn_response({})
    response.text = "<html>Instance hibernating</html>"
    response.headers = {"Content-Type": "text/html"}
    return response


def router(**overrides: Any) -> Callable[..., Any]:
    """A make_sn_request stand-in keyed by the last URL segment."""
    answers: Dict[str, Any] = {
        "sys_user": ME,
        "sys_user_has_role": None,  # roles vs has_role, decided by fields
        "incident": ONE_INCIDENT,
        "sys_dictionary": {"result": []},
        "stats/incident": {"result": {"stats": {"count": "3"}}},
    }
    answers.update(overrides)
    seen = []

    def fake(method, url, timeout, params=None, json_data=None):
        seen.append((method, url))
        assert method == "GET"
        key = "stats/incident" if "/stats/" in url else url.rsplit("/", 1)[-1]
        answer = answers[key]
        if key == "sys_user_has_role" and answer is None:
            answer = ROLES if params["sysparm_fields"] == "role.name" else HELD
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, Mock):
            return answer
        return sn_response(answer)

    fake.seen = seen  # type: ignore[attr-defined]
    return fake


def _run(monkeypatch, capsys, fake, **config) -> tuple[int, str]:
    monkeypatch.setattr(server, "make_sn_request", fake)
    code = run_doctor(make_server_config(**config))
    return code, capsys.readouterr().out


def test_healthy_api_key_identity(monkeypatch, capsys) -> None:
    fake = router()
    code, out = _run(monkeypatch, capsys, fake, auth=API_KEY_AUTH)

    assert code == 0
    assert "header x-sn-apikey" in out
    assert "ok   identity   svc.apikey (API key user)" in out
    assert "itil, snc_read_only (direct grants)" in out
    assert "snc_read_only: write tools hidden" in out
    assert "result: OK" in out
    assert SECRET not in out
    assert {method for method, _ in fake.seen} == {"GET"}


def test_hibernating_instance_fails_reach(monkeypatch, capsys) -> None:
    code, out = _run(monkeypatch, capsys, router(sys_user=_html()))
    assert code == 1
    assert "FAIL reach" in out and "wake the instance" in out
    assert "identity" not in out


def test_bad_credentials_fail_auth(monkeypatch, capsys) -> None:
    fake = router(sys_user=ServiceNowAPIError("Authentication failed (401). Check"))
    code, out = _run(monkeypatch, capsys, fake)
    assert code == 1
    assert "ok   reach" in out and "FAIL auth" in out


def test_unreachable_oauth_token_endpoint_fails_reach(monkeypatch, capsys) -> None:
    import requests

    fake = router(sys_user=requests.ConnectionError("Connection refused"))
    code, out = _run(monkeypatch, capsys, fake)
    assert code == 1 and "FAIL reach" in out


def test_api_key_policy_limit_is_a_warning(monkeypatch, capsys) -> None:
    fake = router(
        **{"stats/incident": ServiceNowAPIError("Authentication failed (401). x")}
    )
    code, out = _run(monkeypatch, capsys, fake, auth=API_KEY_AUTH)
    assert code == 0
    assert "warn aggregate" in out and "policy limit" in out


def test_schema_403_names_the_role(monkeypatch, capsys) -> None:
    fake = router(sys_dictionary=ServiceNowAPIError("Access denied (403). x"))
    code, out = _run(monkeypatch, capsys, fake)
    assert code == 0
    assert "personalize_dictionary" in out


def test_failed_table_read_fails(monkeypatch, capsys) -> None:
    fake = router(incident=ServiceNowAPIError("Access denied (403). x"))
    code, out = _run(monkeypatch, capsys, fake)
    assert code == 1
    assert "FAIL table" in out and "result: FAILED" in out


def test_unreadable_roles_warn_that_hiding_fails_open(monkeypatch, capsys) -> None:
    fake = router(sys_user_has_role=ServiceNowAPIError("Access denied (403). x"))
    code, out = _run(monkeypatch, capsys, fake)
    assert code == 0
    assert "warn roles" in out and "--read-only" in out


def test_read_only_flag_is_reported(monkeypatch, capsys) -> None:
    code, out = _run(monkeypatch, capsys, router(), read_only=True)
    assert "write tools hidden (--read-only)" in out
    assert "flags: --read-only" in out


def test_config_line_never_carries_secrets() -> None:
    oauth = AuthConfig(
        type=AuthType.OAUTH,
        oauth=OAuthConfig(client_id="cid", client_secret=SECRET),
    )
    line = describe_config(make_server_config(auth=oauth))
    assert "client_credentials grant, client cid" in line
    assert SECRET not in line
    basic = describe_config(make_server_config())
    assert "basic, user admin" in basic and "test123" not in basic


def test_doctor_accepts_an_injected_request() -> None:
    doctor = Doctor(make_server_config(), request=router())
    assert doctor.check_table_read() is True
    assert doctor.sample_sys_id == "i1"


class TestCliFlag:
    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch) -> None:
        from tests.test_cli import _CLI_ENV_VARS

        for var in _CLI_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(cli, "load_dotenv", lambda: None)

    def test_config_error_is_reported_on_stdout(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.argv", ["mcp-server-servicenow", "--check"])
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 1
        out = capsys.readouterr().out
        assert "FAIL config" in out and "instance URL is required" in out

    def test_check_never_starts_the_server(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "mcp-server-servicenow",
                "--check",
                "--instance-url",
                "dev1",
                "--username",
                "u",
                "--password",
                "p",
            ],
        )
        with (
            patch("servicenow_mcp.doctor.run_doctor", return_value=0) as doctor,
            patch("servicenow_mcp.server.mcp.run") as run,
        ):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 0
        run.assert_not_called()
        assert doctor.call_args.args[0].instance_url == "https://dev1.service-now.com"
