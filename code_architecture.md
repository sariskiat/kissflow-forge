# Code architecture

The reference is `mcp-server-python-boilerplate`. The dependency direction is
checked by `make architecture`:

```text
MCP tools and Kissflow adapters -> application use cases -> domain
```

## Domain

`src/app/domain/entities/` holds flow, page, and navigation drafts.
`src/app/domain/value_objects/` holds field, style, expression, kind, and
coverage rules. Domain code makes no network or filesystem call. The import
contracts forbid FastMCP, httpx, Pydantic, and other outer-layer libraries.

## Application

`src/app/application/interfaces/` defines ports for each outside service:
flow, app, page, dataset, item, copilot, docs, and artifact files.
`models/requests/` and `models/responses/` hold typed tool data.
`use_cases/<family>/` holds one use case per tool. A use case receives ports,
performs the step order, and raises `ApplicationError` for a refused or failed
operation. It does not import a concrete adapter.

## Infrastructure

`src/app/infrastructure/kissflow/` has one httpx adapter per API family. The
shared `_http.py` sends requests to the validated dev host. The adapters get
the caller's key pair for each call; the pair is not stored in `AppResources`.
`config/settings.py` alone reads the environment and refuses a host that does
not meet the dev-tenant rule.

`mcp/tools/` has nine thin tool modules: flow, app, page, dataset, item,
copilot, intake, design, and meta. Each tool builds a request model, calls one
use case, and turns `ApplicationError` into `ToolError`. `mcp/server.py`
registers them with `create_server()`. `mcp/lifespan.py` opens one shared
`httpx.AsyncClient` and builds the ports. `artifact_writer.py`,
`docs_reader.py`, `playbook.py`, and `capabilities.py` handle filesystem work.

`src/app/main.py` loads settings, starts the lifespan, and chooses stdio or
HTTP. `resources.py` is the one anchor for runtime files at the repo root.

## Deliberate differences from the reference

| Reference | Kissflow Forge | Reason |
|---|---|---|
| One example tool | 61 tools in nine family modules | The existing tool surface must stay the same. |
| One example service | Separate API ports and adapters | Each Kissflow API family has its own wire calls. |
| HTTP only | HTTP with `MCP_HTTP=1`, stdio otherwise | Local work and the live regression use stdio. |
| Database port | No database | The dev tenant holds the app state. |
| No repo-root runtime captures | `src/app/resources.py` anchors `shapes/` and capability docs | Captures and docs refer to repo-relative paths. |
| No artifact writer | `ArtifactWriter` port and `FileArtifactWriter` adapter | Design tools write files without importing the filesystem into use cases. |

Tool names, input schemas, and descriptions are frozen by
`tests/test_tool_surface_snapshot.py`. `scripts/arch_scan.py` checks the layer
seams and the test mirror. `tests/test_boilerplate_conformance.py` checks the
reference layout and recorded differences in `tests/fixtures/tooling_deltas.toml`.

## Evidence boundary

`make verify` checks the local code and offline behavior. `make test-live`
runs against the real dev tenant and is separate from CI. A publish response
alone does not prove the flow works in Kissflow's builder UI; see
`CLAUDE.md > THE RULE`.
