# Kissflow Forge — local Docker POC

Run the MCP server in Docker, stdio transport. Claude Code spawns `docker run` per session.
No OAuth, no hosting, no network. Each colleague runs it on their own machine.

## One-time (you, the owner)

```bash
docker build -t kissflow-forge:local .

# Ship the image to colleagues — pick one:
#   a) registry
docker tag kissflow-forge:local <registry>/kissflow-forge:local
docker push <registry>/kissflow-forge:local
#   b) tarball (no registry)
docker save kissflow-forge:local | gzip > kissflow-forge.tar.gz
```

## Each colleague

1. Get the image:
   - registry: `docker pull <registry>/kissflow-forge:local`
   - tarball:  `docker load < kissflow-forge.tar.gz`
2. `cp kf.env.example kf.env` and fill the 5 secrets (ask the owner for domain + key pair).
3. Add to `.mcp.json` (project) or `~/.claude.json`, fixing the absolute path to `kf.env`:

```json
{
  "mcpServers": {
    "kissflow-forge": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "MCP_HTTP=",
        "--env-file", "/abs/path/to/kf.env",
        "kissflow-forge:local"
      ]
    }
  }
}
```

4. Restart Claude Code, run `/mcp` — tools show as `mcp__kissflow-forge__*`.

## Notes

- `-e MCP_HTTP=` blanks the Dockerfile's `MCP_HTTP=1`, forcing stdio (skips the Google OAuth
  path, which fails closed by design — see server.py:1734).
- `-i` keeps stdin open for the MCP handshake. `--rm` cleans up per session.
- Smoke-test the image without Claude Code:
  ```bash
  printf '%s\n' \
    '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
    '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | docker run -i --rm -e MCP_HTTP= kissflow-forge:local 2>/dev/null
  ```
- WARNING: every colleague sharing `KF_APP` writes to the SAME live dev tenant. Fine for a
  demo, risky if two people build at once.
