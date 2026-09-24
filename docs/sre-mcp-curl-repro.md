# dev-kissflow-mcp — repro for SRE (curl only)

**Symptom:** Claude Desktop cannot add `https://dev-kissflow-mcp.cjexpress.info/mcp` as an MCP
server. The identical container image behind an ngrok tunnel adds fine.

**Root cause (proven below):** the app's redirect for the trailing-slash URL comes back as
`http://` instead of `https://` when it runs behind the mesh. Uvicorn only honours
`X-Forwarded-Proto` from a source IP it trusts, and the default trust list is `127.0.0.1` only.
The Istio sidecar delivers inbound traffic from `127.0.0.6`, which is not trusted, so the app
believes the request arrived over plain HTTP and writes an `http://` `Location`. MCP clients
refuse or mishandle a redirect that downgrades the scheme.

No header is being stripped by the mesh. Session id, SSE and the JSON-RPC calls all pass
through correctly — see test 2-5.

Date of run: 2026-08-18. Endpoint version reported by the server: kissflow-forge 3.4.7.

---

## Test 1 — the failing behaviour (this is the bug)

```bash
curl -sS -D- -o /dev/null https://dev-kissflow-mcp.cjexpress.info/mcp/
```

Actual, through the mesh:

```
HTTP/2 307
server: istio-envoy
location: http://dev-kissflow-mcp.cjexpress.info/mcp     <-- http, scheme downgraded
```

Same image behind ngrok:

```
HTTP/2 307
server: uvicorn
location: https://bronze-grouped-turret.ngrok-free.dev/mcp   <-- https, correct
```

The `http://` URL then 301s back to `https://`, so a browser survives the round trip. An MCP
client does not: it either refuses the insecure hop or loses the POST body across it.

## Test 2 — initialize (works today)

```bash
U=https://dev-kissflow-mcp.cjexpress.info/mcp
curl -sS -D- -X POST $U \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

Actual: `HTTP/2 200`, `content-type: text/event-stream`, `mcp-session-id: <hex>`,
`x-accel-buffering: no`, and the JSON-RPC result body. Nothing stripped.

## Test 3 — full handshake (works today)

```bash
U=https://dev-kissflow-mcp.cjexpress.info/mcp
SID=$(curl -sS -D/tmp/h -o /dev/null -X POST $U \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
  grep -i '^mcp-session-id' /tmp/h | tr -d '\r' | awk '{print $2}')

curl -sS -o /dev/null -w 'initialized: %{http_code}\n' -X POST $U \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

curl -sS -X POST $U \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

Actual: `initialized: 202`, then a 200 carrying the full tool list.

## Test 4 — SSE stream stays open, unbuffered (works today)

```bash
curl -sS -D- -N -X GET $U -H 'Accept: text/event-stream' -H "Mcp-Session-Id: $SID"
```

Actual: `HTTP/2 200`, `content-type: text/event-stream`, `x-accel-buffering: no`, connection
held open with no data. That is healthy — Envoy is not buffering the stream.

## Test 5 — the two 406s are expected, not a proxy fault

```bash
curl -sS $U -H 'Accept: application/json'
# {"error":{"code":-32600,"message":"Not Acceptable: Client must accept text/event-stream"}}
```

The protocol requires `Accept: application/json, text/event-stream` on every request. A client
sending only one of the two gets 406 from the app itself.

---

## Headers that must reach the app / the client

| Direction | Header | Value |
|---|---|---|
| request | `Content-Type` | `application/json` |
| request | `Accept` | `application/json, text/event-stream` (both, comma-joined) |
| request | `Mcp-Session-Id` | value the server minted on initialize |
| request | `MCP-Protocol-Version` | `2025-06-18` |
| response | `mcp-session-id` | must not be stripped; the client cannot make a second call without it |
| response | `content-type` | `text/event-stream` |
| response | `x-accel-buffering` | `no` — keeps the stream flowing |

All seven verified present and intact through the mesh on 2026-08-18.

---

## Proof of the root cause, reproducible locally

Same process, two source addresses. Uvicorn trusts `127.0.0.1` by default and nothing else.

```bash
MCP_HTTP=1 PORT=8899 uv run mcp-server

# source = loopback -> trusted -> X-Forwarded-Proto honoured (this is the ngrok case)
curl -sS -D- -o /dev/null http://127.0.0.1:8899/mcp/ -H 'X-Forwarded-Proto: https'
# location: https://127.0.0.1:8899/mcp

# source = a non-loopback address -> untrusted -> header ignored (this is the sidecar case)
curl -sS -D- -o /dev/null http://192.168.53.85:8899/mcp/ -H 'X-Forwarded-Proto: https'
# location: http://192.168.53.85:8899/mcp        <-- reproduces the mesh behaviour exactly
```

## The fix — one environment variable on the deployment

```
FORWARDED_ALLOW_IPS=*
```

Uvicorn reads this env var directly (`uvicorn 0.52.3`, `Config.__init__`:
`os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")`). FastMCP never sets the value itself, so
the env var is the whole change. `*` is safe here because the pod is only reachable through the
mesh — nothing else can reach the port to forge the header. A tighter value works too if SRE
prefers: the sidecar's inbound source address, `127.0.0.6`.

Verified locally, same untrusted-source request as above, with the variable set:

```
location: https://192.168.53.85:8899/mcp
```

## Acceptance check after the rollout

```bash
curl -sS -D- -o /dev/null https://dev-kissflow-mcp.cjexpress.info/mcp/ | grep -i location
# expected: location: https://dev-kissflow-mcp.cjexpress.info/mcp
```

## Separate, lower priority

`OPTIONS /mcp` returns `405` with no `Access-Control-*` headers, on both the mesh and ngrok, so
it is an application gap rather than a mesh one. It only blocks browser-based clients
(claude.ai in a browser). Claude Desktop and Claude Code do not need it. Fix would be CORS
middleware in the app, exposing `mcp-session-id`.

## Workaround until the rollout

Give clients the URL with no trailing slash: `https://dev-kissflow-mcp.cjexpress.info/mcp`

---

# Image-level proof — the same before and after, against the container SRE will deploy

Date of run: **2026-08-19**. Docker Desktop 29.4.0 on macOS (arm64). Image built from this
repository at commit `e59c8dc`, which is the tree SRE receives.

This section exists because the reproduction above was run against a developer's working tree.
The one below is run against the real container image. It needs no mesh, no cluster and no
proxy: a request entering a container never arrives from loopback, it arrives from the platform's
gateway address — visible in the container's own access log below as `10.254.254.1` — which is
exactly the untrusted-source condition the Istio sidecar creates by delivering from `127.0.0.6`.

One image, two runs. **The only difference between the two runs is the trust list.** No Kissflow
credentials are passed in either run: no `.env` is mounted, no `KF_*` variable is set, and the
container is asked to prove it by counting them.

## Build the image the way the receiving team would

```bash
docker build -t kfforge:proof .
```

Actual, last lines:

```
#12 exporting to image
#12 exporting manifest sha256:a70b5ad1d3b05263edee14ca547d85b88fec19291ad3c4c48802b626841d8ecf done
#12 exporting config sha256:81cb79990ca638967cf4763258bfbfa2c2657bbad8d5858ef30ef1f95fca2d93 done
#12 naming to docker.io/library/kfforge:proof done
#12 DONE 3.1s
```

## Run A — BEFORE: trust list narrowed at run time to uvicorn's own default

```bash
docker run -d --rm --name kfproof -p 8080:8080 -e FORWARDED_ALLOW_IPS=127.0.0.1 kfforge:proof
```

Actual:

```
f604372ba9dad9db55d4a15e0573b9c3f4cee5a8e7a788d7ad5879dd2725f68c
```

Boot log — no credentials, server up, and the source address the app actually sees:

```
[08/19/26 11:43:21] INFO     Starting MCP server                transport.py:361
                             'kissflow-forge' with transport
                             'streamable-http' on
                             http://0.0.0.0:8080/mcp
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
INFO:     10.254.254.1:52483 - "GET /mcp HTTP/1.1" 406 Not Acceptable
```

Credential check inside the running container:

```bash
docker exec kfproof sh -c 'printenv | grep -c "^KF_"'
```

```
0
```

The failing request — trailing slash, `X-Forwarded-Proto: https` supplied:

```bash
curl -sS -D- -o /dev/null http://localhost:8080/mcp/ -H 'X-Forwarded-Proto: https'
```

```
HTTP/1.1 307 Temporary Redirect
date: Wed, 19 Aug 2026 11:43:21 GMT
server: uvicorn
content-length: 0
location: http://localhost:8080/mcp
```

`http://` — the scheme is downgraded. The header was sent and ignored, because
`10.254.254.1` is not on the trust list. This is the mesh failure, reproduced with no mesh.

The same container still serves the protocol correctly with no credentials —
`initialize` → `notifications/initialized` → `tools/list`, tool names counted from the
response body:

```bash
curl -sS -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | grep -o '"name":"[a-z_]*"' | wc -l
```

```
      56
```

## Run B — AFTER: identical image, identical command, trust list left at the image default

```bash
docker run -d --rm --name kfproof -p 8080:8080 kfforge:proof
```

Actual:

```
450e54ccaa074f1b3e72cecea8883af8d2ab88c31592d2db9b1c84ed750126e2
```

Boot log, same shape, same non-loopback source address:

```
                             'kissflow-forge' with transport
                             'streamable-http' on
                             http://0.0.0.0:8080/mcp
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
INFO:     10.254.254.1:42478 - "GET /mcp HTTP/1.1" 406 Not Acceptable
```

Credential check, and the value the image itself ships:

```bash
docker exec kfproof sh -c 'printenv | grep -c "^KF_"'
docker exec kfproof printenv FORWARDED_ALLOW_IPS
```

```
0
*
```

The same request that failed in Run A:

```bash
curl -sS -D- -o /dev/null http://localhost:8080/mcp/ -H 'X-Forwarded-Proto: https'
```

```
HTTP/1.1 307 Temporary Redirect
date: Wed, 19 Aug 2026 11:43:39 GMT
server: uvicorn
content-length: 0
location: https://localhost:8080/mcp
```

`https://` — the scheme is preserved. Tool listing, unchanged, still with no credentials:

```
      56
```

## What the two runs establish

| | Run A (before) | Run B (after) |
|---|---|---|
| Image | `kfforge:proof` | `kfforge:proof`, byte-identical |
| Command | `docker run -d --rm --name kfproof -p 8080:8080 -e FORWARDED_ALLOW_IPS=127.0.0.1` | `docker run -d --rm --name kfproof -p 8080:8080` |
| `FORWARDED_ALLOW_IPS` in the container | `127.0.0.1` | `*` |
| Kissflow credentials in the container | none (`KF_*` count `0`) | none (`KF_*` count `0`) |
| Source address the app sees | `10.254.254.1` | `10.254.254.1` |
| `location` on `/mcp/` | `http://localhost:8080/mcp` | `https://localhost:8080/mcp` |
| Tools listed | 56 | 56 |

Nothing differs but the trust list, and the trust list flips the scheme. That also settles the
override question from the image ticket: the image ships `FORWARDED_ALLOW_IPS=*` in its own
`ENV`, and `-e FORWARDED_ALLOW_IPS=127.0.0.1` at run time overrode it — a stricter platform can
narrow the trust list without a rebuild.

## Teardown

```bash
docker rm -f kfproof
docker ps -a --filter name=kfproof --format '{{.Names}} {{.Status}}'
```

```
kfproof
```

The second command printed nothing: no container from this proof is left behind.
