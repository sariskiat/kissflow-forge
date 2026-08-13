# kissflow-forge MCP — HTTP transport for Cloud Run. NO app-level auth: the HTTP endpoint is
# unauthenticated and writes to a live Kissflow tenant, so it MUST be protected at the network
# layer (private ingress / IAM / VPC). server.main() logs a loud warning when it serves HTTP.
# The engine is pure stdlib apart from fastmcp; the only runtime data are the repo dirs the code
# reads by path (shapes/, docs/capabilities/, skills/) — all anchored at kfforge/../, so the
# working-tree layout must be preserved under /app.
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir "fastmcp>=3"

COPY kfforge/ ./kfforge/
COPY shapes/ ./shapes/
COPY docs/ ./docs/
COPY skills/ ./skills/

# MCP_HTTP flips server.main() from stdio to HTTP. PORT is overridden by Cloud Run at runtime.
ENV MCP_HTTP=1 PORT=8080
EXPOSE 8080

CMD ["python", "-m", "kfforge.server"]
