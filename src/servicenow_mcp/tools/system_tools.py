"""ServiceNow system tools.

Provides system information and property queries.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional, Tuple, cast

from pydantic import Field

from servicenow_mcp.server import mcp, get_config, make_sn_request
from servicenow_mcp.tools import annotations
from servicenow_mcp.middleware.policy import check_identifier
from servicenow_mcp.tools.results import PropertyList, ReferenceReport, TableSchema
from servicenow_mcp.utils.http import (
    ServiceNowAPIError,
    build_url,
    parse_json_response,
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
    result = data.get("result", [])
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
        str, Field(description="The table to look up (e.g., 'incident')")
    ],
    field_name: Annotated[
        Optional[str],
        Field(description="Narrow to one field of the table (e.g., 'assigned_to')"),
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Maximum matches to return per source")
    ] = 50,
) -> ReferenceReport:
    """Where-used for a table or one of its fields: the business rules, client scripts, UI policies, ACLs, script includes and reference fields that touch it.

    Returns names, sys_ids and flags only, never script, condition or ACL
    bodies. Script-include matches are text matches on the name. A source this
    identity can't read is listed in not_assessable; 0 matches may also mean
    rows hidden by an ACL. complete=false means the source hit the limit.
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
            rows = parse_json_response(response, url).get("result", [])
        except ServiceNowAPIError as exc:
            reason = str(exc).split(". ", 1)[0]
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
    return report
