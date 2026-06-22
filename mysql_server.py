import hashlib
import logging
import re
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from sqlalchemy import Engine, text

from config import load_config, load_settings
from tenant import DataSource, Tunnel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Server started")
mcp = FastMCP("mysql-mcp-server")
_config_path = Path(__file__).parent / "config.yaml"

# session_key -> (Tunnel, Engine, last_activity_monotonic)
_sessions: dict[str, tuple[Tunnel, Engine, float]] = {}
_sessions_lock = threading.Lock()

# Set when _sessions is non-empty; reaper blocks on wait() when there is nothing to check.
_session_event = threading.Event()

# Loaded from config.yaml settings.idle_timeout_minutes; overridable at runtime via set_idle_timeout.
try:
    _idle_timeout: float = load_settings(str(_config_path)).idle_timeout_minutes * 60
except Exception:
    _idle_timeout = 300.0


def _session_key(database_server_url: str, schema_name: str) -> str:
    raw = f"{database_server_url}|{schema_name}"
    return hashlib.md5(raw.encode()).hexdigest()[:8]


def _reap_idle_sessions() -> None:
    """Background daemon: disconnect sessions idle longer than _idle_timeout.

    Blocks via _session_event when there are no active sessions so it consumes
    no resources until a connection is established.
    """
    while True:
        _session_event.wait()  # sleep until at least one session exists
        time.sleep(60)
        timeout = _idle_timeout
        if timeout <= 0:
            continue
        now = time.monotonic()
        with _sessions_lock:
            expired = [k for k, (_, _, last) in _sessions.items() if now - last > timeout]
            to_cleanup = [(k, _sessions.pop(k)[0]) for k in expired]
            if not _sessions:
                _session_event.clear()
        for key, tunnel in to_cleanup:
            logger.info("Auto-disconnecting idle session %s", key)
            try:
                tunnel.__exit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing idle session %s: %s", key, e)


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
    name: Annotated[
        str,
        Field(
            description="Optional name for the session (e.g. 'au-prod, us-prod'). If not provided, the session key will be used as the name."
        ),
    ],
) -> str:
    """Connect to the specified database and return the connection details."""
    key = _session_key(database_server_url, schema_name)

    with _sessions_lock:
        existing = _sessions.get(key)

    if existing:
        _, engine, _ = existing
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            with _sessions_lock:
                if key in _sessions:
                    _sessions[key] = (_sessions[key][0], engine, time.monotonic())
            return f"Reusing session {key}: {tenant_name} at {database_server_url}/{schema_name}."
        except Exception:
            # stale session — evict and reconnect
            with _sessions_lock:
                entry = _sessions.pop(key, None)
                if not _sessions:
                    _session_event.clear()
            if entry:
                entry[0].__exit__(None, None, None)

    regions = load_config(str(_config_path))
    matched_region = next(
        (r for r in regions if r.remote_bind_address == region or r.name == name), None
    )
    if not matched_region:
        return f"Region {region} not found in config."

    custom_region = replace(matched_region, remote_bind_address=database_server_url)
    tenant_data_source = DataSource(
        username=custom_region.username,
        password=custom_region.password,
        database_server_url=database_server_url,
        schema_name=schema_name,
    )

    tunnel = Tunnel(tenant_data_source, custom_region)
    try:
        engine = tunnel.__enter__()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as e:
        tunnel.__exit__(None, None, None)
        return f"Connection failed: {database_server_url}. Check VPN and try again. Error: {str(e)}"

    with _sessions_lock:
        _sessions[key] = (tunnel, engine, time.monotonic())
    _session_event.set()
    return f"Connected session {key}: {tenant_name} at {database_server_url}/{schema_name}."


@mcp.tool()
def disconnect(
    session_key: Annotated[
        str, Field(description="Session key returned by connect_to_database")
    ],
) -> str:
    """Dispose of a single persisted database session."""
    with _sessions_lock:
        if session_key not in _sessions:
            return f"Session {session_key} not found. Active sessions: {list(_sessions.keys())}"
        tunnel, _, _ = _sessions.pop(session_key)
        if not _sessions:
            _session_event.clear()
    tunnel.__exit__(None, None, None)
    return f"Session {session_key} disconnected."


_DESTRUCTIVE_SQL = re.compile(
    r"^\s*(DELETE|TRUNCATE|UPDATE|DROP|ALTER|INSERT|REPLACE)\b",
    re.IGNORECASE,
)


def _get_engine(session_key: str) -> Engine:
    with _sessions_lock:
        if session_key not in _sessions:
            raise KeyError(
                f"Session {session_key} not found. Call connect_to_database first."
            )
        tunnel, engine, _ = _sessions[session_key]
        _sessions[session_key] = (tunnel, engine, time.monotonic())
        return engine


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
    with _sessions_lock:
        keys = list(_sessions.keys())
        to_cleanup = [(k, _sessions.pop(k)[0]) for k in keys]
        _session_event.clear()
    for _, tunnel in to_cleanup:
        tunnel.__exit__(None, None, None)
    return f"Disconnected {len(keys)} session(s): {keys}"


@mcp.tool()
def set_idle_timeout(
    minutes: Annotated[
        float,
        Field(description="Idle timeout in minutes. Use 0 to disable auto-disconnect."),
    ],
) -> str:
    """Set how long a session can be idle before it is automatically disconnected."""
    global _idle_timeout
    _idle_timeout = minutes * 60
    if _idle_timeout <= 0:
        return "Auto-disconnect disabled."
    return f"Idle timeout set to {minutes:.1f} minute(s)."


@mcp.tool()
def get_idle_timeout() -> str:
    """Return the current idle timeout setting."""
    if _idle_timeout <= 0:
        return "Auto-disconnect is disabled."
    return f"Idle timeout is {_idle_timeout / 60:.1f} minute(s)."


def main():
    reaper = threading.Thread(target=_reap_idle_sessions, daemon=True)
    reaper.start()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
