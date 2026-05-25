import hashlib
import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from sqlalchemy import Engine, text

from config import load_config
from tenant import DataSource, VPNTunnel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Server started")
mcp = FastMCP("mysql-mcp-server")
_config_path = Path(__file__).parent / "config.yaml"

# Persistent session store: session_key -> (VPNTunnel, Engine)
_sessions: dict[str, tuple[VPNTunnel, Engine]] = {}


def _session_key(database_server_url: str, schema_name: str) -> str:
    raw = f"{database_server_url}|{schema_name}"
    return hashlib.md5(raw.encode()).hexdigest()[:8]


@mcp.tool()
def connect_to_database(
    tenant_name: Annotated[
        str,
        Field(
            description="Full shard hostnames to connect to (e.g. 'acme-shard1,acme-shard2')"
        ),
    ],
    schema_name: Annotated[
        str,
        Field(
            description="Schema name to connect to (e.g. 'performancecentre_global')"
        ),
    ],
    environment: Annotated[
        str,
        Field(
            description="Environment of the database server (e.g. 'production', 'staging')"
        ),
    ],
    database_server_url: Annotated[
        str, Field(description="Database server URL (e.g. 'db.example.com:3306')")
    ],
    region: Annotated[
        str, Field(description="Region of the database server (e.g. 'us-east-1')")
    ],
) -> str:
    """Connect to the specified database and return the connection details."""
    key = _session_key(database_server_url, schema_name)

    if key in _sessions:
        _, engine = _sessions[key]
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return f"Reusing session {key}: {tenant_name} at {database_server_url}/{schema_name}."
        except Exception:
            # stale session — evict and reconnect
            _sessions.pop(key)[0].__exit__(None, None, None)

    regions = load_config(str(_config_path))
    matched_region = next((r for r in regions if r.remote_bind_address == region), None)
    if not matched_region:
        return f"Region {region} not found in config."

    custom_region = replace(matched_region, remote_bind_address=database_server_url)
    tenant_data_source = DataSource(
        username=custom_region.username,
        password=custom_region.password,
        database_server_url=database_server_url,
        schema_name=schema_name,
    )

    tunnel = VPNTunnel(tenant_data_source, custom_region)
    try:
        engine = tunnel.__enter__()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as e:
        tunnel.__exit__(None, None, None)
        return f"Connection failed: {database_server_url}. Check VPN and try again. Error: {str(e)}"

    _sessions[key] = (tunnel, engine)
    return f"Connected session {key}: {tenant_name} at {database_server_url}/{schema_name}."


@mcp.tool()
def disconnect(
    session_key: Annotated[
        str, Field(description="Session key returned by connect_to_database")
    ],
) -> str:
    """Dispose of a single persisted database session."""
    if session_key not in _sessions:
        return f"Session {session_key} not found. Active sessions: {list(_sessions.keys())}"
    tunnel, _ = _sessions.pop(session_key)
    tunnel.__exit__(None, None, None)
    return f"Session {session_key} disconnected."


_DESTRUCTIVE_SQL = re.compile(
    r"^\s*(DELETE|TRUNCATE|UPDATE|DROP|ALTER|INSERT|REPLACE)\b",
    re.IGNORECASE,
)


def _get_engine(session_key: str) -> Engine:
    if session_key not in _sessions:
        raise KeyError(
            f"Session {session_key} not found. Call connect_to_database first."
        )
    return _sessions[session_key][1]


@mcp.tool()
def list_tables(
    session_key: Annotated[
        str, Field(description="Session key from connect_to_database")
    ],
) -> list[str]:
    """Return all table names in the connected schema."""
    engine = _get_engine(session_key)
    with engine.connect() as conn:
        rows = conn.execute(text("SHOW TABLES")).fetchall()
    return [row[0] for row in rows]


@mcp.tool()
def describe_table(
    session_key: Annotated[
        str, Field(description="Session key from connect_to_database")
    ],
    table_name: Annotated[str, Field(description="Table name to inspect")],
) -> list[dict]:
    """Return column definitions (Field, Type, Null, Key, Default, Extra) for a table."""
    engine = _get_engine(session_key)
    with engine.connect() as conn:
        rows = conn.execute(text(f"DESCRIBE `{table_name}`")).mappings().fetchall()
    return [dict(r) for r in rows]


@mcp.tool()
def execute_query(
    session_key: Annotated[
        str, Field(description="Session key from connect_to_database")
    ],
    sql: Annotated[
        str,
        Field(description="SQL to execute (SELECT, SHOW PROCESSLIST, EXPLAIN, etc.)"),
    ],
    limit: Annotated[int, Field(description="Max rows to return", default=100)] = 100,
    confirm: Annotated[
        bool,
        Field(
            description="Must be true to execute destructive statements (DELETE, TRUNCATE, UPDATE, DROP, ALTER, INSERT, REPLACE). Ask the user first, then re-call with confirm=true.",
            default=False,
        ),
    ] = False,
) -> dict:
    """Execute a SQL statement and return the query and up to `limit` rows as dicts."""
    if _DESTRUCTIVE_SQL.match(sql) and not confirm:
        return {
            "query": sql,
            "confirmation_required": True,
            "message": (
                f"'{sql.split()[0].upper()}' is a destructive operation. "
                "Ask the user to confirm, then re-call with confirm=true."
            ),
        }
    engine = _get_engine(session_key)
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = result.mappings().fetchmany(limit)
    return {"query": sql, "rows": [dict(r) for r in rows]}


@mcp.tool()
def disconnect_all() -> str:
    """Dispose of all persisted database sessions."""
    keys = list(_sessions.keys())
    for key in keys:
        tunnel, _ = _sessions.pop(key)
        tunnel.__exit__(None, None, None)
    return f"Disconnected {len(keys)} session(s): {keys}"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
    # logger.info(
    #     connect_to_database(
    #         tenant_name="acme",
    #         schema_name="dev2_amp_nz_250926",
    #         environment="production",
    #         database_server_url="qa-b.c24wcnt1bk9g.ap-southeast-2.rds.amazonaws.com",
    #         region="qa.c24wcnt1bk9g.ap-southeast-2.rds.amazonaws.com",
    #     )
    # )
