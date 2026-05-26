from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from config import load_config
from tenant import DataSource, Tenant

mcp = FastMCP("locate-tenant")
_config_path = Path(__file__).parent / "config.yaml"


def _dataclass_to_dict(ds: DataSource) -> dict:
    return {
        "shard_hosts": ds.shard_hosts,
        "database_server_url": ds.database_server_url,
        "schema_name": ds.schema_name,
        "region": ds.region.remote_bind_address if ds.region else None,
        "name": ds.name,
    }


@mcp.tool()
def locate_tenant(
    host_name: Annotated[
        str, Field(description="Partial hostname to search for (e.g. 'acme')")
    ],
) -> list[dict]:
    """Find which database server and schema a tenant lives on."""
    regions = load_config(str(_config_path))
    results = Tenant().find_by_host_name(host_name, regions)
    return [_dataclass_to_dict(ds) for ds in results]


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
