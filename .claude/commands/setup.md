Set up the locate_tenant project environment using uv.

Steps:
1. If `pyproject.toml` does not exist, run: `uv init --name locate-tenant --no-readme`
2. Add all required dependencies: `uv add sqlalchemy pymysql pyyaml typing-extensions mcp`
3. If `config.yaml` is missing, remind the user to create it based on the structure in CLAUDE.md (devbox + regions keys).

After setup, confirm the venv is ready with: `uv run python -c "import sqlalchemy, mcp; print('OK')`
