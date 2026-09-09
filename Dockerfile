# kissflow-forge MCP — HTTP transport. HTTP mode requires Entra + per-user Kissflow
# authentication; incomplete auth configuration aborts startup rather than falling back to a
# shared process key. Stdio remains the local process-env mode.
# The engine is pure stdlib apart from fastmcp; the only runtime data are the repo dirs the code
# reads by path (shapes/, docs/capabilities/, skills/) — all anchored at kfforge/../, so the
# working-tree layout must be preserved under /app.
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir "fastmcp==3.4.7"

COPY kfforge/ ./kfforge/
COPY shapes/ ./shapes/
COPY docs/ ./docs/
COPY skills/ ./skills/

# MCP_HTTP flips server.main() from stdio to HTTP. PORT is overridden by Cloud Run at runtime.
# FORWARDED_ALLOW_IPS=* makes uvicorn honour X-Forwarded-Proto from ANY peer. uvicorn's default is
# 127.0.0.1 alone, and the Istio sidecar delivers from 127.0.0.6 -- untrusted, so uvicorn believed
# every request was plain HTTP and answered GET /mcp/ with a 307 to an http:// location, a scheme
# downgrade MCP clients refuse (the Claude Desktop connector outage). This container is only ever
# reachable through a proxy, so trusting the forwarding headers is correct for every deployment of
# this image; a platform wanting a narrower list still overrides it at run time, which beats an
# image default. Proven by tests/test_proxy_headers.py; asserted present by tests/test_p0_scaffold.py.
ENV MCP_HTTP=1 PORT=8080 FORWARDED_ALLOW_IPS=*
EXPOSE 8080

CMD ["python", "-m", "kfforge.server"]
