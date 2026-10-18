"""ServiceNow system tools.

Provides system information and property queries.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional, Tuple, cast

from pydantic import Field

from servicenow_mcp.server import (
    get_auth_manager,
    get_config,
    get_sn_bearer_token,
    make_sn_request,
    mcp,
)
from servicenow_mcp.tools import annotations
from servicenow_mcp.middleware.policy import check_identifier
from servicenow_mcp.tools.results import PropertyList, ReferenceReport, TableSchema
from servicenow_mcp.utils.http import (
    ServiceNowAPIError,
    build_url,
    parse_json_response,
    result_rows,
)
from servicenow_mcp.utils.schema import fetch_table_schema
from servicenow_mcp.utils.user import fetch_current_user

logger = logging.getLogger(__name__)


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def get_system_properties(
    query: Annotated[
        Optional[str],
        Field(
            description="Filter query (e.g., 'name=glide.servlet.uri' or 'nameLIKEglide')"
        ),
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Maximum number of properties to return")
    ] = 20,
) -> PropertyList:
    """Query ServiceNow system properties"""
    config = get_config()

    url = build_url(config.api_url, "table", "sys_properties")
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_fields": "name,value,description",
    }
    if query:
        query_params["sysparm_query"] = query

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = result_rows(data)
    return {"count": len(result), "properties": result}


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def get_current_user(
    fields: Annotated[
        Optional[str],
        Field(
            description="Extra sys_user fields to return besides user_name, user_display_name, user_email, user_sys_id and roles"
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get the authenticated user's identity and directly assigned, active roles"""
    config = get_config()
    return fetch_current_user(config.api_url, config.timeout, fields)


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def get_table_schema(
    table_name: Annotated[str, Field(description="The table name to get schema for")],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=1000,
            description="Maximum number of fields to return (own fields first, then inherited)",
        ),
    ] = 200,
    include_inherited: Annotated[
        bool,
        Field(
            description="Include fields inherited from parent tables (e.g. cmdb_ci fields on cmdb_ci_server)"
        ),
    ] = True,
) -> TableSchema:
    """Get the data dictionary (field definitions) for a ServiceNow table, including inherited fields"""
    config = get_config()
    return cast(
        TableSchema,
        fetch_table_schema(
            table_name,
            limit=limit,
            timeout=config.timeout,
            api_url=config.api_url,
            include_inherited=include_inherited,
        ),
    )


def _login_failed(message: str) -> bool:
    """Whether a 401 means the login itself failed, not one table.

    A REST API access policy can leave one table out for an API key, an OAuth
    token or a proxied bearer token, and another try costs no failed login. A
    basic-auth 401, or an OAuth refresh that fails, is the password or secret
    being refused: stop at the first, or every source costs a failed login
    (and ServiceNow may lock the integration user).
    """
    if "token refresh also failed" in message:
        return True
    if get_sn_bearer_token():
        return False
    try:
        return get_auth_manager().config.type.value == "basic"
    except RuntimeError:
        return True


# (source, table, encoded query, fields). Fields are names and flags only:
# script, condition and ACL bodies are never requested.
_Query = Tuple[str, str, str, str]


def _reference_queries(table: str, field: Optional[str]) -> List[_Query]:
    """The where-used queries for a table, or for one field of it."""
    if field is None:
        return [
            ("business_rules", "sys_script", f"collection={table}",
             "sys_id,name,active,when"),
            ("client_scripts", "sys_script_client", f"table={table}",
             "sys_id,name,active,type,field"),
            ("ui_policies", "sys_ui_policy", f"table={table}",
             "sys_id,short_description,active"),
            ("acls", "sys_security_acl", f"name={table}^ORnameSTARTSWITH{table}.",
             "sys_id,name,operation,type,active"),
            ("script_includes", "sys_script_include", f"scriptLIKE{table}",
             "sys_id,name,api_name,active"),
            ("reference_fields", "sys_dictionary", f"reference={table}",
             "sys_id,name,element"),
        ]  # fmt: skip
    return [
        ("business_rules", "sys_script",
         f"collection={table}^scriptLIKE{field}^ORconditionLIKE{field}"
         f"^ORfilter_conditionLIKE{field}",
         "sys_id,name,active,when"),
        ("client_scripts", "sys_script_client",
         f"table={table}^field={field}^ORscriptLIKE{field}",
         "sys_id,name,active,type,field"),
        ("ui_policy_actions", "sys_ui_policy_action", f"table={table}^field={field}",
         "sys_id,ui_policy,field"),
        ("acls", "sys_security_acl", f"name={table}.{field}^ORname={table}.*",
         "sys_id,name,operation,type,active"),
        ("script_includes", "sys_script_include",
         f"scriptLIKE{table}^scriptLIKE{field}",
         "sys_id,name,api_name,active"),
    ]  # fmt: skip


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def find_references(
    table_name: Annotated[
        str,
        Field(max_length=80, description="The table to look up (e.g., 'incident')"),
    ],
    field_name: Annotated[
        Optional[str],
        Field(
            max_length=80,
            description="Narrow to one field of the table (e.g., 'assigned_to')",
        ),
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Maximum matches to return per source")
    ] = 50,
) -> ReferenceReport:
    """Where-used for a table or one of its fields: the business rules, client scripts, UI policies, ACLs, script includes and reference fields that touch it.

    Returns names, sys_ids and flags only, never script, condition or ACL
    bodies. Script matches (script includes; business rules and client scripts
    in field mode) are text matches, so expect false positives. Only this exact
    table is matched: run it again for a parent table (get_table_schema's
    hierarchy) to find rules and ACLs defined there. A source this identity
    can't read (403, or a 401 from an access policy that leaves its table out)
    is listed in not_assessable (under OAuth each such source costs one token
    refresh). Under basic auth the first 401 is an error (a refused password
    looks the same), and so is a refused OAuth secret; rows hidden by an ACL
    are simply missing. complete=false means the source hit the limit.
    """
    for name, value in (("table name", table_name), ("field_name", field_name)):
        check_identifier(name, value)
    config = get_config()
    report: ReferenceReport = {
        "table": table_name,
        "groups": [],
        "not_assessable": [],
    }
    if field_name:
        report["field"] = field_name
    unauthenticated: List[ServiceNowAPIError] = []
    for source, table, query, fields in _reference_queries(table_name, field_name):
        url = build_url(config.api_url, "table", table)
        params: Dict[str, Any] = {
            "sysparm_query": query,
            "sysparm_fields": fields,
            "sysparm_limit": limit,
            "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true",
        }
        try:
            response = make_sn_request("GET", url, config.timeout, params=params)
            rows = result_rows(parse_json_response(response, url))
        except ServiceNowAPIError as exc:
            reason = str(exc).split(". ", 1)[0]
            if "(401)" in reason:
                if _login_failed(str(exc)):
                    raise
                # An access policy may leave out one table: a gap, unless
                # every source says the same.
                unauthenticated.append(exc)
            elif "(403)" not in reason:
                raise  # a timeout or a dead instance is an error, not a gap
            report["not_assessable"].append(
                {"source": source, "table": table, "reason": reason}
            )
            continue
        report["groups"].append(
            {
                "source": source,
                "table": table,
                "count": len(rows),
                "complete": len(rows) < limit,
                "items": rows,
            }
        )
    if (
        unauthenticated
        and len(unauthenticated) == len(report["not_assessable"])
        and not report["groups"]
    ):
        raise unauthenticated[0]  # the identity itself failed
    return report
