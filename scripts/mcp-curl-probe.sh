#!/usr/bin/env bash
# MCP streamable-HTTP probe. Usage: scripts/mcp-curl-probe.sh https://host/mcp
# Run it against the kube URL and the ngrok URL and diff the two outputs.
set -u
U="${1:?usage: $0 <mcp-url>   e.g. https://dev-kissflow-mcp.cjexpress.info/mcp}"
A='Accept: application/json, text/event-stream'
J='Content-Type: application/json'
V='MCP-Protocol-Version: 2025-06-18'
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-probe","version":"0"}}}'

echo "### 1. redirect shape (trailing slash must NOT downgrade to http://)"
curl -sS -D- -o /dev/null --max-time 10 "$U/"       | grep -Ei '^(HTTP|location)' 
curl -sS -D- -o /dev/null --max-time 10 -X POST "$U/" -H "$J" -H "$A" -d "$INIT" | grep -Ei '^(HTTP|location)'

echo "### 2. initialize (expect 200 + content-type: text/event-stream + mcp-session-id)"
curl -sS -D/tmp/mcpprobe.h --max-time 20 -X POST "$U" -H "$J" -H "$A" -H "$V" -d "$INIT" | head -3
grep -Ei '^(HTTP|content-type|mcp-session-id|x-accel-buffering|server)' /tmp/mcpprobe.h
SID=$(grep -i '^mcp-session-id' /tmp/mcpprobe.h | tr -d '\r' | awk '{print $2}')
echo "SID=${SID:-<<< MISSING - proxy stripped the session header >>>}"

echo "### 3. notifications/initialized (expect 202)"
curl -sS -o /dev/null -w '%{http_code}\n' --max-time 20 -X POST "$U" -H "$J" -H "$A" -H "$V" \
  -H "Mcp-Session-Id: $SID" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

echo "### 4. tools/list (expect 200 + a tools array)"
curl -sS --max-time 30 -X POST "$U" -H "$J" -H "$A" -H "$V" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | head -c 240; echo

echo "### 5. GET SSE stream (expect 200 text/event-stream, then hang = healthy)"
curl -sS -D- -o /dev/null --max-time 6 -X GET "$U" -H 'Accept: text/event-stream' -H "$V" \
  -H "Mcp-Session-Id: $SID" | grep -Ei '^(HTTP|content-type|x-accel-buffering)'

echo "### 6. CORS preflight (browser/web clients need allow-origin + expose mcp-session-id)"
curl -sS -D- -o /dev/null --max-time 10 -X OPTIONS "$U" -H 'Origin: https://claude.ai' \
  -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type,mcp-session-id' \
  | grep -Ei '^(HTTP|access-control|allow)'

echo "### 7. OAuth discovery (404 = no auth, fine; 302 to a login page = proxy will break clients)"
for p in /.well-known/oauth-protected-resource /.well-known/oauth-authorization-server; do
  printf '%-50s ' "$p"
  curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 "${U%/mcp}$p"
done
