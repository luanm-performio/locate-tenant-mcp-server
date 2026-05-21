# Locate Tenant MCP Server

An MCP (Model Context Protocol) server that helps locate tenants across multiple database regions and shards. It allows searching for a tenant's database server and schema name based on their hostname.

## Features

- **Tenant Discovery**: Quickly find where a tenant's data is stored.
- **Multi-Region Support**: Searches across different configured database regions.
- **SSH Tunneling**: Automatically handles connections to databases requiring a jumpbox (devbox) for access.
- **FastMCP**: Built using the FastMCP framework for easy tool definition and execution.

## Prerequisites

- [uv](https://github.com/astral-sh/uv) installed on your system.
- Access to the target databases (VPN might be required for some regions).
- SSH access configured if using devbox-required regions.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd locate_tenant
    ```

2.  **Configure the server:**
    Copy the example configuration and update it with your credentials and settings:
    ```bash
    cp config.yaml.example config.yaml
    ```
    Edit `config.yaml` to include your specific database endpoints, usernames, passwords, and devbox details.

3.  **SSH Agent Setup (Crucial for Claude Desktop):**
    For the SSH tunneling to work seamlessly within Claude Desktop, you need to create a stable symlink for your SSH auth socket:
    ```bash
    ln -sf "$SSH_AUTH_SOCK" "$HOME/.ssh/ssh-agent.sock"
    ```

## Claude Desktop Integration

To use this server in Claude Desktop, add the following to your Claude configuration file (typically `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "locate-tenant-server": {
      "command": "uv",
      "args": [
        "--directory", "/Users/<your_user_name>/../locate_tenant",
        "run",
        "server.py"
      ],
      "env": {
        "SSH_AUTH_SOCK": "/Users/<your_user_name>/.ssh/ssh-agent.sock"
      }
    }
  }
}
```

**Note:** Replace `/Users/<your_user_name>/../locate_tenant` with the actual path to your project directory.

## Usage

Once integrated, Claude will have access to the `locate_tenant` tool. You can ask Claude:

- "Find the database for the tenant 'acme'"
- "Where is the 'performancecentre' tenant hosted?"

The tool returns a list of matching data sources, including the shard hosts, database server URL, schema name, and region.

## Development

To run the server locally for testing:

```bash
uv run server.py
```

This will start the server using the `stdio` transport, which is suitable for MCP communication.
