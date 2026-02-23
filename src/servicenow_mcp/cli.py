"""CLI entry point for the ServiceNow MCP server."""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from servicenow_mcp.utils.config import (
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


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")

    parser.add_argument(
        "--instance-url",
        help="ServiceNow instance URL",
        default=os.environ.get("SERVICENOW_INSTANCE_URL"),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=os.environ.get("SERVICENOW_DEBUG", "false").lower() == "true",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("SERVICENOW_TIMEOUT", "30")),
    )
    parser.add_argument(
        "--auth-type",
        choices=["basic", "oauth", "api_key"],
        default=os.environ.get("SERVICENOW_AUTH_TYPE", "basic"),
    )
    parser.add_argument("--username", default=os.environ.get("SERVICENOW_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("SERVICENOW_PASSWORD"))
    parser.add_argument("--client-id", default=os.environ.get("SERVICENOW_CLIENT_ID"))
    parser.add_argument("--client-secret", default=os.environ.get("SERVICENOW_CLIENT_SECRET"))
    parser.add_argument("--token-url", default=os.environ.get("SERVICENOW_TOKEN_URL"))
    parser.add_argument("--api-key", default=os.environ.get("SERVICENOW_API_KEY"))
    parser.add_argument(
        "--api-key-header",
        default=os.environ.get("SERVICENOW_API_KEY_HEADER", "X-ServiceNow-API-Key"),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        help="MCP transport type (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),
        help="Host to bind to for HTTP transport (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8080")),
        help="Port for HTTP transport (default: 8080)",
    )

    return parser.parse_args()


def create_config(args: argparse.Namespace) -> ServerConfig:
    """Create server configuration from parsed arguments."""
    instance_url = args.instance_url
    if not instance_url:
        raise ValueError(
            "ServiceNow instance URL is required (--instance-url or SERVICENOW_INSTANCE_URL)"
        )

    auth_type = AuthType(args.auth_type.lower())
    auth_config: AuthConfig

    if auth_type == AuthType.BASIC:
        if not args.username or not args.password:
            raise ValueError("Username and password required for basic auth")
        auth_config = AuthConfig(
            type=auth_type,
            basic=BasicAuthConfig(username=args.username, password=args.password),
        )

    elif auth_type == AuthType.OAUTH:
        if not args.client_id or not args.client_secret or not args.username or not args.password:
            raise ValueError("client-id, client-secret, username, and password required for OAuth")
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
    )


def main() -> None:
    """Main entry point."""
    load_dotenv()

    try:
        args = parse_args()

        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        config = create_config(args)
        logger.info(f"Starting ServiceNow MCP server for {config.instance_url}")

        # Initialize services before importing tool modules
        from servicenow_mcp.server import mcp, init_services

        init_services(config)

        # Import tool modules to trigger @mcp.tool() registration
        import servicenow_mcp.tools.table_tools  # noqa: F401
        import servicenow_mcp.tools.cmdb_tools  # noqa: F401
        import servicenow_mcp.tools.system_tools  # noqa: F401
        import servicenow_mcp.tools.update_set_tools  # noqa: F401

        logger.info(f"Transport: {args.transport}")
        mcp.run(transport=args.transport, host=args.host, port=args.port)

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
