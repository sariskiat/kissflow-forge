# kissflow-forge MCP — HTTP transport. This server carries no auth provider of its own
# (D1): the SRE gateway in front of it authenticates the caller, and each caller's own
# Kissflow key pair arrives on the request as the X-Access-Key-Id / X-Access-Key-Secret
# headers. Stdio remains the local process-env mode.
#
# The engine's only runtime data are the repo dirs read by path — shapes/, docs/capabilities/,
# skills/ — all resolved through src/app/resources.py, which anchors on the package's own
# location (src/app/.. /..). That is why src/ and those three dirs keep their working-tree
# positions under /app: move one and REPO_ROOT stops pointing at the other three.
FROM python:3.13-slim
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# Dependencies come from uv.lock, not from a bare `pip install fastmcp`. The old image installed
# fastmcp alone and let cryptography, PyYAML, starlette, mcp and pydantic arrive transitively —
# an upstream dependency drop would have broken the running container with no local signal.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

COPY shapes/ ./shapes/
COPY docs/ ./docs/
COPY skills/ ./skills/

# MCP_HTTP flips app.main:main() from stdio to HTTP. PORT is overridden by Cloud Run at runtime.
# FORWARDED_ALLOW_IPS=* makes uvicorn honour X-Forwarded-Proto from ANY peer. uvicorn's default is
# 127.0.0.1 alone, and the Istio sidecar delivers from 127.0.0.6 -- untrusted, so uvicorn believed
# every request was plain HTTP and answered GET /mcp/ with a 307 to an http:// location, a scheme
# downgrade MCP clients refuse (the Claude Desktop connector outage). This container is only ever
# reachable through a proxy, so trusting the forwarding headers is correct for every deployment of
# this image; a platform wanting a narrower list still overrides it at run time, which beats an
# image default. Proven by tests/test_proxy_headers.py; asserted present by tests/test_p0_scaffold.py.
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
ENV MCP_HTTP=1 PORT=8080 FORWARDED_ALLOW_IPS=*
# HTTP_TIMEOUT_SECONDS: the old urllib transport hardcoded TIMEOUT_S=30
# (client.py); Settings' own code default is 10 (the clone's), so this is set
# explicitly here to keep the deployed outbound timeout unchanged once the
# httpx adapters (G8) take over the live traffic this image serves (spec G5).
ENV HTTP_TIMEOUT_SECONDS=30
EXPOSE 8080

CMD ["mcp-server"]
