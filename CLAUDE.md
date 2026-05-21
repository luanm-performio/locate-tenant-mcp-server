# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

MCP server that locates database tenants by hostname across multiple AWS RDS regions. It queries `performancecentre_global.data_source` on each region's DB, tunnelling through an SSH jumpbox where required.

## Setup

Run `/setup` (project slash command) to initialise the uv environment and install dependencies.

Manual equivalent:
```bash
uv init --name locate-tenant --no-readme
uv add sqlalchemy pymysql pyyaml typing-extensions mcp
```

`config.yaml` contains live credentials — never commit it. Structure:
```yaml
devbox:
  ca_file: "/path/to/global-bundle.pem"
  ssh_pkey: "/path/to/.ssh/id_rsa"
  username: "your_username"
  jumpbox: "jumpbox.example.com"
regions:
  - remote_bind_address: "db.region.rds.amazonaws.com"
    remote_bind_port: 3306
    devbox_required: true   # routes through jumpbox
    username: "db_user"
    password: "db_password"
```

## Commands

```bash
uv run python tenant.py          # ad-hoc search (hardcoded "amp" host filter in __main__)
uv run mcp dev server.py         # run MCP server in dev mode (once server.py exists)
uv run mcp install server.py     # install into Claude Desktop
```

## Architecture

| File | Role |
|---|---|
| `config.py` | `Region` / `DevBox` frozen dataclasses; `load_config()` parses `config.yaml` |
| `tunnel.py` | `SSHTunnel` — wraps `subprocess.Popen` for `ssh -L` port-forward; `get_free_port()` picks a local port |
| `tenant.py` | `DevTunnel` context manager (SSH + SQLAlchemy engine lifetime); `Tenant.find_by_host_name()` |

**Data flow:** `load_config` → `Region` list → per-region `DevTunnel` context manager → SQLAlchemy `LIKE %host%` query on `data_source.shard_hosts` → list of `DataSource` results.

`DevTunnel.__enter__` starts the SSH tunnel (if `devbox_required`), creates the engine pointed at the local port, and tears both down in `__exit__`.

## MCP Tool to Build

Expose `locate_tenant(host_name: str, regions: list[str] | None = None)` using `fastmcp`:

```python
from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field

mcp = FastMCP("locate-tenant")

@mcp.tool()
def locate_tenant(
    host_name: Annotated[str, Field(description="Partial hostname to search for")],
) -> list[dict]:
    ...
```

- Annotate all parameters with `Field(description=...)` — MCP exposes these to the LLM
- `SSHTunnel.start()` uses `time.sleep(1)`; replace with `asyncio.sleep` if making the tool async
- Return structured dicts/dataclasses, not formatted strings
