# Code Architecture

Adapted from the AI-CoE `mcp-server-python-boilerplate`. Where this repo deviates from that
template, the deviation is written down here with its reason — an undocumented deviation is
just drift.

## 1. Architecture goal

Keep the Kissflow build logic independent of FastMCP, of the builder HTTP API, and of the
filesystem.

```text
Infrastructure  --->  Application  --->  Domain
```

Dependencies point inward. This is **enforced**, not asserted: `make architecture` runs
import-linter over the contracts in `pyproject.toml` and fails the build when an edge turns
around.

## 2. Layers

### Domain — `src/app/domain/`

The normalized Kissflow node-graph and pure operations on it: `types` (frozen structs, closed
enums), `graph`, `expr`, `pages`, `nav`, `coverage`.

**Should** be plain Python and stdlib, independently testable, and free of any notion that a
Kissflow tenant exists over a network.

**Should not** import `fastmcp`, `mcp`, `starlette`, `httpx`, `pydantic`, `cryptography`, or
`yaml` — contract-enforced.

### Application — `src/app/application/`

Use cases over the domain: `engine` (offline planning), `tools` (framework-agnostic dict-in/
dict-out logic), `verify` (the health check), `compare`, `querybank`, `intake/` (the
11-dimension AppSpec, the grilling script, and the AppSpec→BuildPlan compiler), and `design/`
(the confirm-before-you-build diagrams and mockups).

**Should** depend on the domain and on nothing outward.

**Should not** import `fastmcp`, `mcp`, `starlette`, `httpx`, `cryptography`, or `yaml` —
contract-enforced. `pydantic` is permitted for DTOs, matching the boilerplate.

### Infrastructure — `src/app/infrastructure/`

Everything that touches an external system: `kissflow/client.py` (THE WRITE PATH),
`kissflow/auth.py` (Entra + per-user OAuth), `kissflow/dataplane.py` (the documented
`/process` item API), `kissflow/pages_live.py`, `capabilities.py` and `playbook.py` (filesystem
readers), and `mcp/server.py` (the FastMCP adapter).

The MCP adapter stays **thin**: it declares the tool surface and delegates. Business rules
belong in the application layer, wire shapes in the domain.

### Composition root — `src/app/main.py`

Chooses the transport and binds the port. That is a deployment decision, so it lives outside
the adapter. Entry points: `mcp-server` and `python -m app.main`.

## 3. Deviations from the boilerplate, and why

| Boilerplate | Here | Why |
|---|---|---|
| `ty check .` with no rule overrides | same, plus two rules off for `tests/**` | Every one of the 440 diagnostics was fixed except two classes, both stated once in `pyproject.toml`: `too-many-positional-arguments` (32, all `pytest.skip(...)` — ty cannot see through pytest's `@_with_exception` decorator, and NEITHER the positional nor the keyword spelling type-checks) and `invalid-assignment` (35, instance-level method stubbing on test doubles — 27 already carried mypy's own ignore). Every other rule stays live in tests. |
| `E501` enforced | `ignore = ["E501"]` | Measured: p95=98, p99=106 — the code is already written to ~100. The 594-line tail is captured Kissflow wire strings, copilot prompt text, and long explanatory comments; 128 of those cannot be split without mangling a literal. `ruff format` owns layout instead, and IS gated. |
| `asyncpg` / PostgreSQL | none | This engine has no database. Its state lives in the Kissflow tenant. |
| `httpx` as a runtime dep | dev-only | The builder client uses `urllib` from the stdlib. `httpx` only drives the ASGI app in tests. |
| FastMCP lifespan holding resources | module-level `mcp` | The builder client is constructed per call from per-user credentials, not held open across the process. There is no pool to manage, so there is no lifespan to manage it. |
| Package is self-contained | `src/app/resources.py` | `shapes/`, `docs/capabilities/` and `skills/` are runtime data at the repo root, because `docs/capabilities/*.md` cross-references its captures as repo-relative `shapes/...` strings. One module anchors them; it sits outside the three layers, so importing it crosses no boundary. |

## 4. Error handling

Technical failures stay inside infrastructure until translated. Nothing below the MCP boundary
raises a raw `urllib` error at a caller, and no tool returns a Kissflow credential, a token, or
a stack trace to an MCP client.

## 5. The rule that outranks all of this

An HTTP 200 and a clean publish prove nothing about whether the flow actually works — see
`CLAUDE.md > THE RULE`. Clean layering does not make a wrong wire shape right. The only
reliable oracle is a UI-built artifact to diff against.
