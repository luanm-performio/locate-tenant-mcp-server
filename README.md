# Locate Tenant MCP Server

Two MCP servers for locating and querying tenant databases across multiple AWS RDS regions, using Cloudflare WARP to switch virtual networks per region.

## Servers

| Server | File | Purpose |
|---|---|---|
| `locate-tenant` | `server.py` | Find which DB server/schema a tenant lives on by hostname |
| `mysql-mcp-server` | `mysql_server.py` | Connect to a tenant DB and run SQL queries interactively |

## Features

- **Tenant Discovery**: Search for a tenant's database server and schema by partial hostname.
- **Multi-Region Support**: Queries all configured regions in parallel.
- **Cloudflare WARP**: Switches WARP virtual networks per region automatically — no SSH jumpbox needed.
- **Persistent Connections**: `mysql_server` caches DB connections by session key so the VPN switch only happens once.
- **Schema Introspection**: List tables and describe columns so the LLM can write correct SQL.
- **Safe Query Execution**: Destructive statements (DELETE, TRUNCATE, UPDATE, DROP, etc.) require explicit confirmation before running.

## Prerequisites

- [uv](https://github.com/astral-sh/uv) installed.
- [Cloudflare WARP](https://one.one.one.one/) installed at `/Applications/Cloudflare WARP.app`.
- WARP logged in and connected, with virtual networks configured for each region.

## Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd locate_tenant
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Configure:**
   ```bash
   cp config.yaml.example config.yaml
   ```
   Edit `config.yaml` with your DB credentials and WARP `virtual_network_id` for each region. Omit `virtual_network_id` for regions that don't require a VPN switch.

## Configuration

```yaml
regions:
  - remote_bind_address: "rds20.example.ap-southeast-2.rds.amazonaws.com"
    remote_bind_port: 3306
    username: "your_username"
    password: "your_password"
    virtual_network_id: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"  # WARP vnet ID; omit if not needed
```

Find your WARP virtual network IDs with:
```bash
/Applications/Cloudflare\ WARP.app/Contents/Resources/warp-cli vnet list
```

## Claude Desktop Integration

Add both servers to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "locate-tenant": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/locate_tenant",
        "run",
        "server.py"
      ]
    },
    "mysql-mcp-server": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/locate_tenant",
        "run",
        "mysql_server.py"
      ]
    }
  }
}
```

## Usage

### Locate a tenant

> "Find the database for the tenant 'acme'"

Claude calls `locate_tenant("acme")` and returns the shard hosts, DB server URL, schema name, and region for every match.

### Query a tenant database

> "Show me scheduled jobs with status RUNNING for acme"

Claude will:
1. Call `locate_tenant` to find the DB server and schema.
2. Call `connect_to_database` — switches WARP to the right VNet and returns a `session_key`.
3. Call `list_tables` and `describe_table` to understand the schema.
4. Call `execute_query` with the appropriate SQL.

For destructive queries (DELETE, UPDATE, TRUNCATE, DROP, etc.), Claude will ask for your confirmation before executing.

### mysql_server tools

| Tool | Description |
|---|---|
| `connect_to_database` | Opens a persistent connection; returns a `session_key` |
| `list_tables` | Lists all tables in the connected schema |
| `describe_table` | Shows column definitions for a table |
| `execute_query` | Runs SQL; requires `confirm=true` for destructive statements |
| `disconnect` | Closes a single session |
| `disconnect_all` | Closes all open sessions |

## Development

```bash
uv run python server.py          # run locate-tenant server via stdio
uv run python mysql_server.py    # run mysql-mcp-server via stdio
uv run mcp dev server.py         # run in MCP dev inspector
```
