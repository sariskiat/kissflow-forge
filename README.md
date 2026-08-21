# kissflow-forge

Generalised Kissflow builder engine + MCP server. Builds flows, forms, workflows,
visibility matrices and app pages on a Kissflow dev tenant from a structured spec —
with confirmation artifacts (draw.io diagrams + HTML mockups) before any build.

Dev-only by construction: the client refuses any domain without `dev-`.
Target app comes from `KF_APP` (no default). Secrets live in `.env` (never committed).

    uv run --with pytest --with fastmcp --no-project pytest -q   # offline suite
    # MCP: .mcp.json boots kfforge.server for any Claude Code session in this folder

Setting it up on a new machine: `docs/notes/SETUP.md`. Using an already-hosted server as a
non-technical end user: `docs/connect-claude-desktop.md`.
