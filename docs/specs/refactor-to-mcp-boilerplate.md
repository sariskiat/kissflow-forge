# Spec: refactor kissflow-forge to the MCP boilerplate architecture


|                  |                                                                                                                                                                                                      |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status           | Approved on 2026-09-22: the user started `/implement` on this file. P0 in progress.                                                                                                                  |
| Branch           | `feat/refactor-architecture-boundary-withsre`                                                                                                                                                        |
| Base             | `develop @ 9651283`                                                                                                                                                                                  |
| Date             | 2026-09-22                                                                                                                                                                                           |
| Decisions source | The comparison page (private artifact, rev 11): decisions D1 to D5, questions Q1 to Q9. This file restates them as contracts.                                                                        |
| Reference        | The boilerplate `mcp-server-python-boilerplate`, `main @ 67c22ae`, cloned on 2026-09-22 at `/Volumes/Projects/dev/mcp-server-python-boilerplate`. Every "the clone has" line below was read from it. |
| Reader           | The agent or engineer who implements one goal at a time. Read section 5 (terms) first.                                                                                                               |
| Progress         | Section 16, the checklist. Tick an item only after its check ran green, and write the commit next to it.                                                                                             |


Every line number below points at `develop @ 9651283`. Re-check a line number before you edit, because earlier goals move code.

## 1. Business consult

**Problem.** kissflow-forge has the boilerplate's folders but not its wiring. Each of the 61 tools builds its own client, orders its own steps, and shapes its own errors. Settings are read on 23 lines in 5 files. Auth lives in the repo. No code takes a snapshot before a write (`server.py:37-44`). SRE cannot deploy and own this server the way it owns the other MCP servers, because the shape is different.

**Timeline vs resources.** The change touches 24,813 lines in `src/app` and 48 test files. One engineer with an agent works one phase at a time (section 9). A phase ends when every gate in section 8 that applies to it is green. The next phase does not start before that. The refactor itself needs nothing from SRE. Only the HTTP deployment behind the gateway needs SRE's answers (section 14). The user sets the dates. This file sets no dates.

**Beyond expectation.** After the refactor, every write takes a snapshot first, so a bad write has a rollback artifact. Every failure reaches the client as one `ToolError` with a code. A missing setting stops the process at boot, not at the first call. SRE deploys the server with the same shape as every other MCP server.

## 2. Researcher's view

**Truth condition (Q1, the hard way).** The refactor is done when every check in section 8 is green at the same time. No check is waived.

**NULL baseline.** Before any module moves, G0 records the numbers in section 15. They are `make verify`, the coverage percentage, the live pass count as the user's account, the line count per file, and the scan numbers. Every later claim is "before → after" against that table.

**The claim we can make at the end.**

> On `develop @ <sha>`, with the boilerplate clone at `<sha>`, all five gates pass.

The five gates are conformance, contracts, scans, surface snapshot, and live regression as account `KF_DEV_ACCOUNT_ID`. Nothing more.

**The smaller claim wins.** We do not claim fewer lines. We do not claim faster calls. We claim structural equality with the boilerplate and unchanged tool behaviour.

**What we cannot prove offline.** THE RULE in `CLAUDE.md`: an HTTP 200 proves nothing about a flow. Only the live suites and a check in the Kissflow builder UI prove the write path. That is why the live regression is a gate and not an option.

**The lazy way, rejected.** Keep today's layout and add Settings, `ToolError` and a lifespan. Skip ports and use cases. Keep urllib. The user rejected it (Q1). The evidence agrees: the lazy way leaves the 61 tools in charge of step order, so the snapshot gap stays open.

## 3. Six decision moves

1. **Truth condition.** Section 8.
2. **Demote the failing part.** The wiring fails, not the logic. The pure logic (the graph ops, the health check, intake, design) moves but does not change. The wiring (tools, client, env reads, errors) is rebuilt.
3. **Take the goal literally.** "The hardest way to match the boilerplate." Not "inspired by". Every slot, the same names. Every difference is listed with a reason (G1).
4. **Design the eval before the system.** G0 builds the conformance test, the surface snapshot and the scans before any module moves.
5. **Run the NULL baseline before new machinery.** G0 is the first goal.
6. **Write contracts, not descriptions.** Every goal has a DoD that a script or a test can check.

## 4. Decisions


| Id  | Contract                                                                                                                                                                                                                                                                                                                                                                                                         | Rejected alternative                                                                                                                                                              | Evidence                                                                                                                             |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| D1  | Auth leaves the repo. SRE's Entra gateway sits in front of a public endpoint. `auth.py` is deleted.                                                                                                                                                                                                                                                                                                              | Keep the OAuth proxy in the repo. Rejected: two auth layers, and SRE owns Entra.                                                                                                  | `auth.py` 799 lines, 10 env reads, 13 env values at `kf.env.example:19-35`.                                                          |
| D2  | Everything else matches the boilerplate's structure and tech stack. HARD rule. The clone is the reference.                                                                                                                                                                                                                                                                                                       | The lazy way (section 2).                                                                                                                                                         | The page's box-by-box table.                                                                                                         |
| D3  | The Dockerfile and the SRE CI chain stay. A new Dockerfile comes later.                                                                                                                                                                                                                                                                                                                                          | Rewrite the Dockerfile now. Rejected: out of scope.                                                                                                                               | `Dockerfile:37`, `.gitlab-ci.yml:22-27`.                                                                                             |
| D4  | Dev tenant only, by construction. We provide `KF_DEV_DOMAIN` and `KF_DEV_ACCOUNT_ID`. The Kissflow key pair is the connector's credential. The org admin pastes it into the connector's Request headers. In production it is the Kissflow team's central ID. For testing it can be that ID or a personal one. "Production" means the production deployment of the connector, not the Kissflow production tenant. | Each user brings their own pair through the server's OAuth flow. Rejected: no OAuth flow after D1. A shared pair in `kf.env`. Rejected: the pair must be swappable per connector. | Claude's connector docs (2026-09-22): the org owner adds the connector, "Request headers" hold fixed credentials sent on every call. |
| D5  | Modular by family. One module per Kissflow API family at every layer: adapter, port, use-case folder, tool module, DTO folder.                                                                                                                                                                                                                                                                                   | One wide `FlowRepository` port. Rejected by the user.                                                                                                                             | 44 of 61 tools reach exactly one family, 3 reach two, 14 reach none (scan, 2026-09-22).                                              |


**Hard rules. Never break these.**

- HR1. Dev tenant only, by construction. No tool takes a domain or account argument. Every outbound URL starts with `https://{KF_DEV_DOMAIN}`. Settings refuses a domain without `dev-`.
- HR2. The key pair is never a tool argument, never logged, never stored by the server.
- HR3. The tool surface does not change: 61 names, the same parameter schemas, the same docstrings.
- HR4. No phase merges with a red gate.
- HR5. The boilerplate clone is the reference. When this file and the clone differ, the clone wins, and this file is updated. Never guess a boilerplate detail.
- HR6. The live suites never run in CI (`Makefile:10`). They run on the engineer's machine with the engineer's `.env`.

## 5. Terms

One meaning each. Use these words and no synonyms.


| Term        | Meaning                                                                                                                                                  |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| boilerplate | `mcp-server-python-boilerplate`, the reference repo.                                                                                                     |
| clone       | The local checkout of the boilerplate at `/Volumes/Projects/dev/mcp-server-python-boilerplate`, exported as `BOILERPLATE_DIR`.                           |
| slot        | One folder or file the boilerplate has, such as `application/use_cases/`.                                                                                |
| family      | One group of Kissflow API calls: flow, app, page, dataset, item, copilot. Plus three families for tools that call no Kissflow API: intake, design, meta. |
| port        | One ABC in `application/interfaces/<family>.py`.                                                                                                         |
| adapter     | One class in `infrastructure/kissflow/<family>.py` that implements a port with httpx.                                                                    |
| use case    | One class in `application/use_cases/<family>/<tool>.py` with `execute(request) -> response`.                                                             |
| tool        | One `@mcp.tool` function in `infrastructure/mcp/tools/<family>.py`.                                                                                      |
| thin        | A tool that only maps arguments to a request DTO, calls one use case, and maps `ApplicationError` to `ToolError`.                                        |
| key pair    | `KF_DEV_ACCESS_KEY_ID` and `KF_DEV_ACCESS_KEY_SECRET`, as one `KissflowKeyPair`.                                                                         |
| pool        | The one `httpx.AsyncClient` that the lifespan opens.                                                                                                     |
| surface     | The 61 tool names, their parameter JSON schemas, and their docstrings.                                                                                   |
| snapshot    | A read of the draft before any write to it.                                                                                                              |
| scan        | A static check in `scripts/arch_scan.py`.                                                                                                                |
| gate        | A check in section 8.                                                                                                                                    |
| live        | A test that hits the real Kissflow dev tenant.                                                                                                           |
| the account | `KF_DEV_ACCOUNT_ID` with the user's key pair in the user's `.env`.                                                                                       |
| fake        | An in-memory class in `tests/fakes/` that implements a port.                                                                                             |


## 6. Goals

Every goal has the same seven parts. Write the TDD test first. Watch it fail. Then make it pass.

### G0. Baseline and gates

- **Goal.** Record the NULL baseline and build the gates before any module moves.
- **Why.** Every later claim is "before → after". Without the baseline there is no claim.
- **Files to touch.** `Makefile`. `test-live` runs all four live files, 31 tests, not three files and 30. The coverage comment says 89 and `pyproject.toml:139` says 90, so fix the comment. This file, section 15.
- **Files to create.** `scripts/arch_scan.py` (every scan in section 8, one function each, `python -m scripts.arch_scan --json`). `tests/test_arch_scan.py`. `tests/fixtures/tool_surface.json` (frozen from `develop @ 9651283`: for each tool, its name, its parameter JSON schema, and the SHA-256 of its docstring). `tests/test_tool_surface_snapshot.py`. `tests/test_boilerplate_conformance.py` (skips with a clear message when `BOILERPLATE_DIR` is unset).
- **TDD test.** `test_arch_scan.py` runs every scan against a fixture package under `tests/fixtures/arch_scan_bad/` that has one violation of each kind. Each scan finds its violation. `test_tool_surface_snapshot.py` builds the server, lists the tools, and compares them to the fixture. It passes on `develop` today. `test_boilerplate_conformance.py` is red on `develop` today. That is expected.
- **DoD.** `make test-live` green as the account, counts recorded. Coverage percentage recorded. Line count per file recorded. Scan numbers recorded. The surface fixture committed. The conformance test exists and is red.
- **Outcome.** Section 14 is filled. The gates exist before the work.

### G1. The clone and the copied contracts

- **Goal.** Clone the boilerplate outside this repo. Copy its tooling sections into `pyproject.toml` word for word.
- **Why.** D2 and HR5. The blindness test (`tests/test_p0_scaffold.py:20-25`) reads every text file under the repo root, so the clone must live outside the repo.
- **Files to touch.** `pyproject.toml`: `[tool.ruff]`, `[tool.ty]`, `[tool.importlinter]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`, `requires-python`. `.python-version`.
- **Files to create.** `tests/fixtures/tooling_deltas.toml`, one entry per difference that must stay, with a reason. The clone is already at `/Volumes/Projects/dev/mcp-server-python-boilerplate`. Export `BOILERPLATE_DIR` to that path.
- **The clone has.** `[tool.ruff]` with `target-version = "py313"`, `line-length = 88`, `select = ["E", "F", "I", "B", "UP", "SIM"]`, double quotes. `[tool.ty.environment]` with `python-version = "3.13"`, `root = ["./src"]`. Three import-linter contracts: layers inward, domain forbids `pydantic`, `fastmcp`, `asyncpg`, `httpx`, `dotenv`, application forbids `asyncpg`, `httpx`, `fastmcp`, `dotenv`. `[tool.pytest.ini_options]` with `pythonpath = ["src"]`. Coverage `fail_under = 90`. Dev group: `pytest`, `pytest-cov`, `ruff`, `ty`, `pytest-asyncio`, `import-linter`. `[tool.uv]` with `default-groups = ["dev"]`, `package = true`.
- **Known deltas, each with its reason.** `name`, `version`, `description`: ours. `dependencies`: only what our code imports, so no `asyncpg`, and `fastmcp==4.0.2` stays pinned exactly (`pyproject.toml:9-10`). The `live` pytest marker (HR6). `pythonpath` stays `["src"]`, so `conftest.py` moves to `tests/conftest.py` (G14). Our own import-linter forbidden lists are deleted. The clone's lists replace them word for word.
- **User decisions, 2026-09-22.** Line length is a ratchet: `line-length = 88` and `E501` on, as the clone. Every file that fails `E501` after the reformat sits on `[tool.ruff.lint.per-file-ignores]`. That list is a delta that only shrinks: a goal that moves or deletes a file takes it off and fixes its lines, and the list is empty at P6. ty retires by goal: the 32 `pytest.skip(...)` calls become `raise pytest.skip.Exception(...)` (ty 0.0.81 accepts that spelling), `invalid-assignment` narrows to the four test files that G3, G8 and G10 delete, and `root` keeps `"."` until G14. `httpx` stays in the dev group until G5. `[build-system]` and `[tool.hatch]` stay (D3).
- **TDD test.** `test_boilerplate_conformance.py::test_tooling_sections_equal`: each listed section equals the clone's after normalisation, except the entries in `tooling_deltas.toml`.
- **DoD.** `make architecture` green with the copied contracts. The tooling test green. Every delta has a reason.
- **Outcome.** The same tooling as the boilerplate.

### G2. Settings

- **Goal.** One `Settings` object, checked at boot, the only reader of environment variables.
- **Why.** The boilerplate's `config/settings.py`. Today 23 lines in 5 files read the environment, one of them in the domain (`graph.py:306`).
- **Files to touch.** `src/app/main.py:19-26`. `src/app/domain/graph.py:306` (the template id becomes a parameter). `src/app/infrastructure/kissflow/client.py:133-196` (`KfConfig` takes its values from `Settings`, the `{prefix}` logic and the non-dev branch are deleted). `src/app/infrastructure/mcp/server.py:141`. `.env.example` (only the values below). `kf.env.example` is folded into it and deleted. User decision, 2026-09-22: the env file is `.env`, as the clone.
- **Files to create.** `src/app/infrastructure/config/__init__.py`. `src/app/infrastructure/config/settings.py`. `tests/unit/infrastructure/config/test_settings.py`.
- **Fields.** `KF_DEV_DOMAIN` (required, must contain `dev-`). `KF_DEV_ACCOUNT_ID` (required). `KF_APP` (optional). `KF_PROCESS_TEMPLATE` (optional). `PORT` (default 8080). `MCP_HTTP` (bool, default false). `KF_DEV_ACCESS_KEY_ID` and `KF_DEV_ACCESS_KEY_SECRET` (optional, stdio only, see G4). `HTTP_TIMEOUT_SECONDS` (default 10, as the clone).
- **The clone has.** A frozen dataclass `Settings` with lowercase fields, and `load_settings()` that calls `load_dotenv()`, reads `os.getenv`, and raises `RuntimeError("<KEY> is required")` for a missing key. Copy that shape. Do not add pydantic-settings. The `dev-` check raises `RuntimeError("refusing non-dev domain ...")` in `load_settings()`.
- **TDD test.** A missing `KF_DEV_DOMAIN` stops startup with an error that names the key. A domain without `dev-` is refused with the message `refusing non-dev domain`, the same as `client.py:142` today. The scan `env_reads_outside_settings` returns zero.
- **DoD.** The scan returns zero. Tests green. `KF_DOMAIN`, `KF_ACCOUNT_ID`, `KF_ACCESS_KEY_ID`, `KF_ACCESS_KEY_SECRET` are gone from code and from `.env.example`.
- **Outcome.** Boot fails fast, and it names the missing key.

### G3. Delete auth

- **Goal.** Delete `auth.py` and the OAuth provider.
- **Why.** D1. SRE's gateway does Entra.
- **Files to touch.** `src/app/infrastructure/mcp/server.py:85-86`, `:140-141`, `:170` (`auth=_oauth` becomes no auth). `kf.env.example:16-35` (deleted). `pyproject.toml` (delete a dependency only when no module imports it any more, for example `cryptography`).
- **Files to delete.** `src/app/infrastructure/kissflow/auth.py`. `tests/test_oauth_per_user.py`.
- **Keep.** `tests/test_proxy_headers.py` and the `ProxyHeadersMiddleware` setup. They are not auth. They guard the https-downgrade outage fixed in commit `8f73a84`.
- **TDD test.** The server is created with no auth provider (assert on the `FastMCP` instance). `import app.infrastructure.kissflow.auth` raises `ModuleNotFoundError`. The proxy-header tests still pass.
- **DoD.** `auth.py` gone. `grep -rn "fastmcp.server.auth" src` returns nothing. Dependencies pruned. Tests green.
- **Outcome.** 799 lines and 13 env values gone.

### G4. The key pair from request headers

- **Goal.** Read the caller's key pair from two request headers on every call. In stdio mode read it from `.env`, through `Settings`.
- **Why.** D4 and Q8.
- **Header names.** `X-Access-Key-Id` and `X-Access-Key-Secret`. These are the names Kissflow itself uses (`client.py:206`), so the adapter forwards them unchanged. Rejected alternative: custom names such as `X-Kissflow-Key-Id`. More mapping, no gain.
- **Files to touch.** `src/app/infrastructure/mcp/server.py:277-300` (`_client()` calls `caller_keys()` until G12 deletes `_client()`).
- **Where the pair is used.** The adapters call `caller_keys(settings)` when they sign a request (G8). The tool edge calls it first, before the use case, so a missing pair fails fast (G12). Use cases and ports never see it.
- **Files to create.** `src/app/infrastructure/kissflow/credentials.py`: `KissflowKeyPair` (frozen dataclass, `__repr__` masks the secret) and `caller_keys(settings) -> KissflowKeyPair`. Over HTTP it reads `get_http_headers(include={"x-access-key-id", "x-access-key-secret"})` from `fastmcp.server.dependencies` (present in 4.0.2). A missing header raises `ToolError("no Kissflow key pair on this call")`. In stdio mode it reads the optional pair from `Settings`. A missing pair raises the same `ToolError`. `tests/unit/infrastructure/kissflow/test_credentials.py`.
- **TDD test.** (1) Both headers present → a pair. (2) A header missing over HTTP → `ToolError`, and a spy port records zero calls. (3) stdio → the pair from `Settings`. (4) `repr`, `str` and the log never contain the secret (assert with `caplog`). (5) No tool parameter is named like a key (assert against the surface fixture).
- **DoD.** `grep -rn "X-Access-Key-" src` shows only `credentials.py` and the adapters' outbound signing. Tests green.
- **Outcome.** HR2 holds.

### G5. Lifespan and the pool

- **Goal.** One `httpx.AsyncClient` pool, opened at startup and closed at shutdown, shared by every adapter.
- **Why.** The boilerplate's `mcp/lifespan.py`. Today `_client()` builds a client per call (`server.py:277`).
- **Files to touch.** `src/app/main.py`. `src/app/infrastructure/mcp/server.py`.
- **The clone has.** `app_lifespan(server, settings)` opens the clients, builds every adapter once, and yields `{"resources": AppResources(...)}`. `AppResources` is a frozen dataclass whose fields are the ports. The pool is `httpx.AsyncClient(timeout=settings.http_timeout_seconds)`, and each adapter takes the client and its `base_url`.
- **Files to create.** `src/app/infrastructure/mcp/lifespan.py`: `app_lifespan(server, settings)` yields `{"resources": AppResources(flow, app, page, dataset, item, copilot, docs)}`, one field per port, built once around the shared pool. `tests/unit/infrastructure/mcp/test_lifespan.py`.
- **TDD test.** The lifespan opens one pool with the timeout from `Settings` and closes it on exit (use `httpx.MockTransport`). Every field of `AppResources` is an instance of its port. `AppResources` holds no credentials (assert no attribute holds a pair).
- **DoD.** Tests green. `_client()` is deleted in G12.
- **Outcome.** No per-call connection setup.

### G6. Exceptions

- **Goal.** Replace `Err` return values with raised exceptions. Convert to `ToolError` at the tool edge. Build the server with `mask_error_details=True`.
- **Why.** The boilerplate's `exceptions.py`. Q4.
- **Files to touch.** `src/app/infrastructure/mcp/server.py` (every `isinstance(x, Err)` site, deleted as the tools become thin in G12). `src/app/infrastructure/kissflow/client.py` (raise instead of return, deleted in G8).
- **The clone has.** `ApplicationError(message, code="APPLICATION_ERROR")` with `.message` and `.code`, and `RepositoryError` and `ExternalServiceError` as subclasses with their own default codes. The tool does `except ApplicationError as exc: raise ToolError(exc.message) from exc`.
- **Files to create.** `src/app/application/exceptions.py`: the clone's three classes, same signatures. Codes: `REPOSITORY_ERROR`, `EXTERNAL_SERVICE_ERROR`, `CONFLICT`, `VERIFY_FAILED`, `NOT_FOUND`, `REFUSED`. `tests/unit/application/test_exceptions.py`.
- **Mapping.** Today's `Err.kind` (`client.py:113`): `http` from the builder API → `RepositoryError`. `http` from the item API → `ExternalServiceError`. `conflict` → `RepositoryError`, code `CONFLICT`. `verify` → `ApplicationError`, code `VERIFY_FAILED`. `config` → no runtime error, `Settings` stops the process at boot.
- **TDD test.** One test per mapping row. The tool edge: a use case raises `ApplicationError("VERIFY_FAILED", "…")` and the client receives a `ToolError` with that message. `test_mcp_surface.py` asserts `mask_error_details is True`.
- **DoD.** `class Err` deleted. The scan `iserror_dicts` returns zero. Every tool test asserts `ToolError` on failure.
- **Outcome.** One error path. Note for Q4: the failure result changes from a dict to a `ToolError`. The parameter schemas do not change (HR3). G16 updates the playbook text that mentions `isError`.

### G7. Ports

- **Goal.** One ABC per family in `application/interfaces/`.
- **Why.** D5.
- **Files to touch.** None.
- **Files to create.** `src/app/application/interfaces/__init__.py`, `flow.py` (`FlowRepository`), `app.py` (`AppRepository`), `page.py` (`PageRepository`), `dataset.py` (`DatasetRepository`), `item.py` (`ItemService`, from `DataPlaneClient` at `dataplane.py:53`), `copilot.py` (`CopilotService`), `docs.py` (`DocsReader`, for the meta family, see G13). `tests/fakes/<family>.py`, one fake per port. `tests/unit/application/interfaces/test_ports.py`.
- **Seed method list.** The 51 client-side names the tools use today (scan, 2026-09-22), grouped by family. Add a method to a port only when a use case calls it.
- **TDD test.** Each fake instantiates and implements every abstract method. Each ABC alone raises `TypeError` on instantiation. The scan `port_methods_without_use_case` is enabled from P3. G7 adds ports before G11 adds their use cases, so G7 may raise that one ceiling in `tests/test_arch_scan.py` to the number of port methods it adds, and says so in its commit. G11 lowers it, and it is 0 when G11 is done. No other goal may raise a ceiling (review of G0, 2026-09-22).
- **DoD.** Seven ABCs. One fake per port. `ty check` green.
- **Outcome.** The application layer depends on ports only.

### G8. Adapters, the httpx rewrite

- **Goal.** One adapter per family that implements its port with httpx (async). It signs each request with the caller's pair. It builds every URL from `Settings`. It translates errors.
- **Why.** D2 (httpx), D5, D4.
- **Files to delete at the end of P4.** `src/app/infrastructure/kissflow/client.py` (6,582 lines). `pages_live.py` (844). `dataplane.py` (675).
- **Shape.** Each adapter takes `client: httpx.AsyncClient`, `base_url: str` and `settings` in `__init__`, as the clone's `ExampleExternalClient(client=..., base_url=...)` does. It is built once in the lifespan. It calls `caller_keys(settings)` when it signs, so the pair is per request and never stored.
- **Files to create.** `src/app/infrastructure/kissflow/flow.py`, `app.py`, `page.py`, `dataset.py`, `item.py`, `copilot.py`. `_http.py` (shared: `sign(request, pair)`, `translate(exc) -> RepositoryError | ExternalServiceError`, the conflict rule: HTTP 409, or 400 with `KISSFLOW_ERROR_04602` (`client.py:105`), → `CONFLICT`). `tests/unit/infrastructure/kissflow/test_<family>.py` with `httpx.MockTransport`. `tests/fixtures/recorded/<family>/*.json`, recorded once as below.
- **Invariant. State it before you code.** For every outbound request `r`: `r.url.host == settings.KF_DEV_DOMAIN` and `r.headers["X-Access-Key-Id"] == pair.key_id` and `r.headers["X-Access-Key-Secret"] == pair.key_secret`. A test transport asserts this on every request in every adapter test.
- **TDD test.** Per port method, a differential test. While the old client still exists, wrap it with a recording shim. Call old and new with the same input. Compare method, URL and body. Keep the recordings as fixtures. Then error translation tests per status. Then the conflict test. Then the invariant transport on every test.
- **DoD.** The three old files deleted. `grep -rn urllib src` returns nothing. The scan `adapter_methods_without_port` returns zero. `make test-live` green as the account. Coverage at 90 or above.
- **Outcome.** Async adapters, one per family. HR1 holds by construction.

### G9. Domain

- **Goal.** Entities, value objects and `DomainError`. The dict operations in `graph.py` become `FlowDraft` methods with no dict fallback. The rules in `verify.py` become `FlowDraft` methods. The coverage rows become a value object.
- **Why.** D2. The user marked the entity row as forced. Q6.
- **Files to touch.** `src/app/domain/graph.py` (3,040 lines) → `entities/flow_draft.py`. `pages.py` → `entities/page_draft.py`. `nav.py` → `entities/navigation.py`. `types.py`, `expr.py` → `value_objects/`. `coverage.py` → `value_objects/coverage.py`. `src/app/application/verify.py` (816 lines) → `entities/flow_draft.py` (`problems()`).
- **Files to create.** `src/app/domain/entities/__init__.py`, `flow_draft.py`, `page_draft.py`, `navigation.py`. `src/app/domain/value_objects/__init__.py`, `expression.py`, `field_type.py`, `field_spec.py`, `coverage.py`. `src/app/domain/exceptions.py` (`DomainError(row_key, reason)`). Mirrored tests under `tests/unit/domain/`.
- **TDD test.** Re-point `test_graph.py`, `test_pages.py`, `test_nav.py`, `test_expr.py`, `test_verify.py`, `test_coverage.py`, `test_section_layout.py`, `test_field_types.py` at the entity API with the same assertions. They are the regression net for the domain. New: `FlowDraft.from_wire(d)` then `.to_wire()` round-trips byte-equal on every file in `tests/fixtures/*.json` and `shapes/*.json`. `DomainError` is raised when compile hits a `refuses-loudly` row (`coverage.py:39`). The scan `dict_draft_in_domain_api` returns zero.
- **DoD.** The domain has exactly `entities/`, `value_objects/`, `exceptions.py` and `__init__.py`. The scan returns zero. Tests green. `graph.py:306` is gone.
- **Outcome.** Rich entities, no dict fallback.

### G10. Models

- **Goal.** Pydantic request and response DTOs per tool under `models/requests/<family>/` and `models/responses/<family>/`. `AppSpec` as a Pydantic model. `serde.py` and the `coerce_*` helpers deleted.
- **The clone has.** `models/requests/get_item_request.py` with `GetItemRequest(BaseModel)` and `models/responses/get_item_response.py` with `GetItemResponse(BaseModel)`. One class per file. Copy that split.
- **Why.** The boilerplate's `models/`. D2.
- **Files to touch.** `src/app/application/intake/schema.py` (799 lines) → `models/requests/intake/app_spec.py`. `src/app/application/tools.py:158-457` (`coerce_*`, deleted). `tools.py:16-157` (`list_field_types`, `plan_*` → use cases in G11).
- **Files to delete.** `src/app/application/intake/serde.py` (219 lines). `tests/test_serde.py` (replaced).
- **Files to create.** `src/app/application/models/requests/<family>/<tool>_request.py` and `src/app/application/models/responses/<family>/<tool>_response.py`, 61 pairs, one class per file. `tests/unit/application/models/requests/<family>/test_<tool>_request.py` and the same under `responses/`.
- **Rule for HR3.** A tool keeps today's flat parameters. It builds the request DTO inside. The DTO is not the tool parameter. So the parameter schema stays equal to the surface fixture.
- **TDD test.** Round-trip tests replace `test_serde.py`: `model_dump()` then `model_validate()` is byte-equal on the fixtures. Validation tests replace the `coerce_*` tests in `test_tools.py` with the same invalid inputs, now raising `ValidationError`. The surface snapshot test stays green.
- **DoD.** `serde.py` gone. `coerce_*` gone. The surface snapshot equal.
- **Outcome.** Pydantic parses and serialises.

### G11. Use cases

- **Goal.** 61 use cases, one per tool, under `use_cases/<family>/`, each with `execute(request) -> response` and its ports injected in `__init__`.
- **Why.** D2, D5, Q2.
- **Files to touch.** `src/app/infrastructure/mcp/server.py` (every tool body moves). `src/app/application/compare.py`, `engine.py`, `intake/compile.py`, `intake/questions.py`, `design/*.py`, `querybank.py` (5,740 lines) move into their family folders. A pure helper that one family shares lives in `use_cases/<family>/_<name>.py`.
- **Files to create.** `src/app/application/use_cases/<family>/<tool>.py`, 61 files. `use_cases/flow/_write_order.py`, one function that every write use case calls. It runs the write order from `CLAUDE.md`: snapshot → dry-run → apply → read back → publish → audit. `tests/unit/application/use_cases/<family>/test_<tool>.py`, 61 files, with the fakes.
- **Invariant. State it before you code.** For every write use case `W` and fake port `F`: the first call `W` makes on `F` is `get_draft` (the snapshot). The response carries `snapshot_version`, the version read. This field is additive.
- **TDD test.** Per use case, the happy path with the fake, and the failure path raising `ApplicationError` with the right code. The write-order test runs over every write use case. A test asserts that the list of write use cases is complete against the surface. A tool is a write when its name starts with one of the prefixes below.
Prefixes: `forge_set`, `forge_add`, `forge_apply`, `forge_create`, `forge_delete`, `forge_build`, `forge_publish`, `forge_rename`, `forge_member`, `forge_grant`, `forge_share`, `kf_apply`, `kf_create`, `kf_set`, `kf_publish`.
- **DoD.** 61 use case files and 61 test files. The scan `port_methods_without_use_case` returns zero. The write-order test green for every write.
- **Outcome.** The order of steps lives in use cases. The snapshot gap at `server.py:37-44` closes.

### G12. Thin tools and `create_server()`

- **Goal.** Nine thin tool modules. `server.py` exposes `create_server(lifespan)` that registers them. `main.py` wires the lifespan and the server.
- **The clone has.** `create_server(lifespan: LifespanFactory) -> FastMCP` builds `FastMCP(name, lifespan=lifespan, mask_error_details=True)` and defines the tool inside it. The tool takes `ctx: Context`, reads `ctx.lifespan_context["resources"]`, builds the use case with the ports from `AppResources`, awaits `execute(request)`, and converts `ApplicationError` to `ToolError(exc.message)`. `main.py` calls `load_settings()`, wraps `app_lifespan` in an `asynccontextmanager`, and runs `create_server(lifespan)`. Copy that shape. Ours keeps one delta: `MCP_HTTP` unset runs stdio for local work and the live regression.
- **Why.** The boilerplate's `server.py` and `main.py`. Q7, D5, HR3.
- **Files to touch.** `src/app/infrastructure/mcp/server.py` (2,594 lines → `create_server()` and nothing else). `src/app/main.py`.
- **Files to create.** `src/app/infrastructure/mcp/tools/__init__.py`, `flow.py`, `app.py`, `page.py`, `dataset.py`, `item.py`, `copilot.py`, `intake.py`, `design.py`, `meta.py`. Each exposes `register(mcp: FastMCP) -> None`, and `create_server()` calls the nine. `tests/unit/infrastructure/mcp/tools/test_<family>.py`.
- **Rule.** A tool does three things. It maps its arguments to the request DTO. It calls one use case, built from the ports in `ctx.lifespan_context["resources"]`. It converts `ApplicationError` to `ToolError`. Before the use case it calls `caller_keys()` once, so a missing pair fails fast. It keeps today's docstring verbatim.
- **TDD test.** The surface snapshot equal (61 names, schemas, docstring hashes). `test_mcp_surface.py` and `test_tool_claims.py` green. Per family: argument mapping, `ApplicationError` → `ToolError`, no key pair → `ToolError` before the use case. The scans `tool_module_imports_own_family_only` and `module_level_fastmcp` return zero.
- **DoD.** `server.py` has no tool body. `_client()` gone. Tests green.
- **Outcome.** A thin edge.

### G13. Playbook and capabilities

- **Goal.** Keep `infrastructure/playbook.py` and `infrastructure/capabilities.py` as adapters that read the repo's own docs. The meta use cases reach them through the `DocsReader` port.
- **Why.** Q1 says every module maps to one slot. These two read the filesystem, so they are adapters. `resources.py` stays the one filesystem anchor.
- **Files to touch.** `src/app/infrastructure/playbook.py`, `capabilities.py` (implement `DocsReader`).
- **Files to create.** `src/app/application/interfaces/docs.py` (in G7). `tests/fakes/docs.py`.
- **TDD test.** `test_playbook.py` and `test_capabilities.py` pass through the port with the same assertions.
- **DoD.** The meta tools call use cases that depend on `DocsReader` only.
- **Outcome.** No filesystem read outside infrastructure.

### G14. Tests layout

- **Goal.** `tests/unit/` mirrors `src/app/` one to one, as the clone does. The live suites move to `tests/integration/`. `tests/conftest.py` replaces every external client.
- **Why.** D2. The clone has `tests/unit/<path>/test_<module>.py` for every module, `tests/unit/test_main.py`, and `tests/integration/README.md` as the placeholder for tests that need a live system.
- **Files to touch.** The 48 test files move to `tests/unit/<path>/test_<module>.py`. The four `test_live_*.py` files move to `tests/integration/`. `conftest.py` moves to `tests/conftest.py`, so `pythonpath` can equal the clone's `["src"]`. `Makefile` (`test-live` points at `tests/integration/`).
- **Files to create.** `tests/unit/<path>/__init__.py` as the clone does. `src/__init__.py`, as the clone has it. `tests/integration/README.md` that says how to run the live suites and that they never run in CI (HR6).
- **TDD test.** The scan `tests_mirror_src`: for each `src/app/<p>/<m>.py` there is `tests/unit/<p>/test_<m>.py`, with an allowlist for `__init__.py`. `tests/unit/test_main.py` exists.
- **DoD.** The scan returns zero. `make test` green. Coverage at 90 or above. `make test-live` green as the account from the new path.
- **Outcome.** A test is one path away from its module.

### G15. Docker and CI

- **Goal.** Keep the Dockerfile and the CI chain. `make verify` runs lint and then the tests with coverage at 90, as the clone's `verify` does. Live never runs in CI.
- **Why.** D3. HR6.
- **The clone has.** `verify: lint` followed by `uv run pytest --cov=src/app --cov-fail-under=90 -q`. A two-stage CI, `lint` and `test`, on `python:3.13-slim`. Ours keeps the SRE chain instead of the two stages. That delta is D3, listed in `tooling_deltas.toml`.
- **Files to touch.** `Makefile` (`verify` as the clone, `test-live` kept). `Dockerfile` (the entry point `mcp-server` stays). `.gitlab-ci.yml` (the `quality-gate` job runs `make verify`).
- **Files to create.** None.
- **TDD test.** None. CI config is checked by the pipeline.
- **DoD.** The pipeline is green on the merge request.
- **Outcome.** The same deploy path as today.

### G16. Docs and ADR

- **Goal.** Update the manual and record the decisions.
- **Why.** `tests/test_engine_doc.py` is a contract over `CLAUDE.md` and `docs/engine/*.md`. `~/.claude/docs/fde.md` asks for an ADR per load-bearing choice.
- **Files to touch.** `CLAUDE.md` (Layout, Commands). `code_architecture.md` (start from the clone's, then add the family fan-out). `docs/engine/13-deploying-the-mcp-server.md` (keep every marker phrase the test requires). `docs/connect-claude-desktop.md`. `docs/demo-user-setup.md`. `docs/security-findings.md`. `.env.example`. `README.md`. `skills/kissflow-forge-builder/SKILL.md` (the error shape, Q4).
- **Files to create.** `docs/adr/0007-boilerplate-architecture-and-connector-key-pair.md` (D1 to D5, Q8).
- **TDD test.** `tests/test_engine_doc.py` green. `tests/test_p0_scaffold.py` green.
- **DoD.** No document describes `kfforge/`, `auth.py`, `Err`, `_client()` or urllib as current.
- **Outcome.** The manual matches the code.

## 7. Big-picture tests

**BP1. Offline end to end.** `tests/test_big_picture.py`. Build the server with `create_server(Settings(...))`. Give the lifespan a pool that uses `httpx.MockTransport` and replays `shapes/*.json`. Call the tools through the in-process client with the two headers set. Run the build order from `CLAUDE.md`, steps 1 to 12. The steps are: create the process, members, fields, a table, the workflow, assignees, goto gates, the visibility matrix, events, styles, publish, and the health check. Assert each response. Assert that the first outbound call of every write is a GET of the draft. Assert that every outbound host equals `KF_DEV_DOMAIN`.

**BP2. Live end to end as the account.** `make test-live`, 31 tests, with the user's `.env`. `test_live_lifecycle.py` already walks step 13: create an item, fill it, submit it. The pass count after equals the pass count before (section 15). Run it at the end of P1, P3, P4, P5 and P6.

**BP3. Conformance.** `tests/test_boilerplate_conformance.py` against `BOILERPLATE_DIR`. Green at the end of P6.

## 8. Gates

All of these are green at the same time when the refactor is done. A phase gate is the subset that its goals enable.


| Gate              | Check                                                                                                                                                                                                                                                                                  | Command                                                                 |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| 1 Conformance     | Every slot in the clone exists here with the same name and role. Every module under `src/app` maps to one slot. The tooling sections equal the clone's, deltas excepted.                                                                                                               | `BOILERPLATE_DIR=… uv run pytest tests/test_boilerplate_conformance.py` |
| 2 Contracts       | The copied import-linter contracts pass. Lint, format and types pass.                                                                                                                                                                                                                  | `make lint`                                                             |
| 3 Scans           | `env_reads_outside_settings` = 0. `module_level_fastmcp` = 0. `iserror_dicts` = 0. `adapter_methods_without_port` = 0. `port_methods_without_use_case` = 0. `tool_module_imports_own_family_only` = 0. `tests_mirror_src` (against `tests/unit/`) = 0. `dict_draft_in_domain_api` = 0. | `uv run pytest tests/test_arch_scan.py`                                 |
| 4 Behaviour       | The surface fixture equals the live surface. Every failure is a `ToolError`. `make test` green. Coverage at 90 or above (`pyproject.toml:139`).                                                                                                                                        | `make verify`, `make test-coverage`                                     |
| 5 Live regression | `make test-live` green as the account, 31 tests, pass count equal to the baseline.                                                                                                                                                                                                     | `make test-live`                                                        |


Reported, never targeted: the line count per file, and the scan numbers from section 15.

## 9. Sequence


| Phase | Goals          | Gate after the phase                                                                            | Needs                                                         |
| ----- | -------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| P0    | G0, G1         | Section 15 filled. Gate 2 green. Gate 1 red, expected. Gate 5 baseline recorded.                | The clone. The user's `.env`.                                 |
| P1    | G2, G3, G4, G5 | Gates 2, 4. Scan `env_reads_outside_settings` = 0. Gate 5 through stdio (the pair from `.env`). | Nothing external.                                             |
| P2    | G6, G9, G10    | Gates 2, 4. Surface equal. Scans `iserror_dicts`, `dict_draft_in_domain_api` = 0.               | Nothing external.                                             |
| P3    | G7, G11        | Gates 2, 4, 5. The write-order invariant green. Scan `port_methods_without_use_case` = 0.       | Nothing external.                                             |
| P4    | G8             | Gates 2, 3 (adapters), 4, 5. The biggest risk. Run gate 5 twice, on two days.                   | Nothing external. Gate 5 runs through stdio with your `.env`. |
| P5    | G12, G13, G14  | Gates 2, 3 (all), 4, 5.                                                                         | Nothing external.                                             |
| P6    | G15, G16       | Gates 1 to 5, all green. Done.                                                                  | The merge request pipeline.                                   |


Order inside a phase: write the goal's TDD test, watch it fail, make it pass, run the phase gate, commit with the user's approval. One goal per commit.

## 10. Risks and guards


| Risk                                       | Guard                                                                                     |
| ------------------------------------------ | ----------------------------------------------------------------------------------------- |
| The httpx rewrite changes a request shape. | The differential recordings in G8, and gate 5 twice in P4.                                |
| Async tools change FastMCP behaviour.      | The surface snapshot, and BP1 through the in-process client. The pure logic stays sync.   |
| A doc or fixture trips the blindness test. | `tests/test_p0_scaffold.py` runs in every gate 4.                                         |
| The clone differs from the page.           | HR5. The clone wins. Update this file and the page.                                       |
| The gateway is not ready when P4 ends.     | Gate 5 runs through stdio with the same adapters. Only the HTTP deployment waits for SRE. |
| The surface drifts.                        | The fixture from G0 and `test_tool_surface_snapshot.py`.                                  |
| Coverage falls as files are deleted.       | Run `make test-coverage` at every phase gate.                                             |
| A use case skips the snapshot.             | The write-order invariant in G11, run over every write use case.                          |


## 11. Day 2 owners


| What                                           | Owner                |
| ---------------------------------------------- | -------------------- |
| The gateway, header pass-through, the endpoint | SRE                  |
| The central Kissflow key pair and its rotation | The Kissflow team    |
| The connector and its Request headers          | The Claude org admin |
| This repo, the gates, the ADR                  | The AI CoE           |


## 12. Q10, settled: the clone's `.claude/` is copied

The clone ships `.claude/` with three parts. Two agents: `reviewer.md` and `writer.md`. Two Stop hooks: `lint-on-stop.sh` and `test-coverage-on-stop.sh`. A `settings.json` that denies reads of `.env` and runs both hooks at every stop. The user chose to copy it on 2026-09-22. Two lines differ, each listed in `tooling_deltas.toml`. The reviewer diffs against `develop`, because that is this repo's trunk. The deny list also covers `kf.env`, the name of the Docker env file in `docs/notes/SETUP.md:120-128`. The hooks run `make lint` and the tests with coverage at every stop. A red test wakes the agent until it is green, at most twice per session.

## 13. Out of scope

- The Kissflow production tenant. D4.
- A line-count target. Q1 reports numbers, it does not target them.
- New tools, new fields, new shapes. HR3.
- The content of the AppSpec schema. It converts, it does not change.
- A new Dockerfile. D3.

## 14. Asks for SRE, before the HTTP deployment

The refactor does not wait for these. Every phase, gate 5 included, runs through stdio with the engineer's `.env`. These items decide whether the deployed server behind SRE's gateway works. They are properties of the gateway and the network, which SRE owns (D1).

1. Required. Pass `X-Access-Key-Id` and `X-Access-Key-Secret` through the gateway unchanged. Do not log them. If the gateway drops them, every call over HTTP fails with `no Kissflow key pair on this call`. Status: told to SRE on 2026-09-22.
2. Dropped on 2026-09-22. We do not ask SRE to forward the Entra identity. Each person logs in with their own Azure identity at the gateway. On Kissflow everyone acts as the central ID. Our server does not learn who the person is, and it does not need to (D1). Audit trail: the gateway's access log holds person to request. Kissflow's audit holds central ID to change.
3. Required. Allow Anthropic's network to reach the endpoint. Every connector call comes from Anthropic's cloud, not from the user's laptop. Status: SRE said yes on 2026-09-22.
4. Required for the production connector only. Send us the public endpoint URL and the port, for the connector settings. Status: deferred until the production test.
5. Open, found in the Stage D review (2026-09-23). `out_dir` of `forge_render_flow_diagram`, `forge_render_schema_diagram`, `forge_render_mockups` and `forge_request_confirmation` is a path the caller chooses, and the server creates directories and writes files there wherever its process may write. The old server did the same. Over HTTP, every connector user can do it. Decide before the HTTP deployment: a fixed base directory in HTTP mode, a read-only filesystem outside it, or both.
6. Open, found in the Stage D review (2026-09-23), older than this branch. Only `forge_create_flow` accepts a caller-chosen `extra["template_path"]`; the domain reads that file and clones its content into the tenant. `kf_create_process` and `forge_create_process` use the operator's `KF_PROCESS_TEMPLATE` setting instead. Over HTTP, a caller of `forge_create_flow` can make the server read any JSON file its process may read and copy it into a flow the caller can read back. The read also sits in the domain layer, where no I/O belongs. Decide before the HTTP deployment: refuse a caller path in HTTP mode, or allow only paths under `shapes/`; move the read behind a port.

Alternative to item 1, for the case where the pair must not sit in Anthropic's connector store. The gateway holds the central pair and adds the two headers itself. Then the connector sends no headers. This moves the secret to SRE's gateway config and is a bigger ask.

## 15. Baseline (G0 fills this table)


| Number                                                     | Before (develop @ 9651283)                                                                                                                                                                                                                                                                                                                                                                                                            | After    |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `make verify`                                              | pass, 2,278 tests passed, 31 skipped (2026-09-22)                                                                                                                                                                                                                                                                                                                                                                                     |          |
| Coverage, `make test-coverage`                             | 90.04%: 8,839 statements, 694 missed, 3,548 branches, 424 partial (2026-09-22)                                                                                                                                                                                                                                                                                                                                                        |          |
| Live, `make test-live` as the account                      | Attempt 1 (`b083431`, 2026-09-22 11:48 UTC, dev guard forced with `KF_DOMAIN=`): 5 passed, 3 failed, 23 skipped. The 3 failures: `KF_APP` points to an app the tenant no longer has (404, `KISSFLOW_ERROR_04207`). Attempt 2 (after the user trimmed `.env` to `KF_DEV_DOMAIN` and `KF_DEV_ACCOUNT_ID`): 0 passed, 31 skipped, no call made (no key pair, no `KF_APP`). Blocked until the key pair is back on the engineer's machine. |          |
| `src/app` lines                                            | 24,813                                                                                                                                                                                                                                                                                                                                                                                                                                |          |
| `server.py` / `client.py` / `graph.py` / `auth.py` lines   | 2,594 / 6,582 / 3,040 / 799                                                                                                                                                                                                                                                                                                                                                                                                           |          |
| Env reads outside settings                                 | 23 lines in 5 files                                                                                                                                                                                                                                                                                                                                                                                                                   | 0        |
| Client-side names used by tools                            | 51 (scan, 2026-09-22). A second count by the inventory of the same night found 52 direct names. Both numbers stay.                                                                                                                                                                                                                                                                                                                    |          |
| Tools per family                                           | flow 25, app 14, intake 9, page 3, design 3, meta 3, copilot 2, dataset 1, item 1                                                                                                                                                                                                                                                                                                                                                     | same     |
| Public functions referenced by no other module             | 0 orphaned (name-level scan). The inventory of the same night found one: `client.py` `apply_fields_and_layout` (lines 1997-2037) has no caller in `src/`, only tests. Both findings stay.                                                                                                                                                                                                                                             |          |
| Tool surface                                               | 61 tools, fixture from G0                                                                                                                                                                                                                                                                                                                                                                                                             | equal    |
| Scan `env_reads_outside_settings` (`scripts/arch_scan.py`) | 23                                                                                                                                                                                                                                                                                                                                                                                                                                    | 0        |
| Scan `module_level_fastmcp`                                | 1                                                                                                                                                                                                                                                                                                                                                                                                                                     | 0        |
| Scan `iserror_dicts`                                       | 75                                                                                                                                                                                                                                                                                                                                                                                                                                    | 0        |
| Scan `adapter_methods_without_port`                        | 102                                                                                                                                                                                                                                                                                                                                                                                                                                   | 0        |
| Scan `port_methods_without_use_case`                       | 0 (no ports yet)                                                                                                                                                                                                                                                                                                                                                                                                                      | 0        |
| Scan `tool_module_imports_own_family_only`                 | 0 (no tool modules yet)                                                                                                                                                                                                                                                                                                                                                                                                               | 0        |
| Scan `tests_mirror_src`                                    | 27                                                                                                                                                                                                                                                                                                                                                                                                                                    | 0        |
| Scan `dict_draft_in_domain_api`                            | 47                                                                                                                                                                                                                                                                                                                                                                                                                                    | 0        |
| Conformance with `BOILERPLATE_DIR` set                     | 3 passed, 3 failed (20 slots missing, 20 modules unmapped, 4 repo paths missing)                                                                                                                                                                                                                                                                                                                                                      | 6 passed |


## 16. Checklist

Tick an item only after its check ran green. Write the commit next to it. Keep every failed check and its number. Never erase one after a later pass.

### Setup

- [x] Q10: the clone's `.claude/` is copied (`67edda3`).
- [x] The user approved this file by starting `/implement` (2026-09-22).
- [x] Decision, 2026-09-22: line length is a ratchet (G1).
- [x] Decision, 2026-09-22: ty deltas retire by goal (G1).
- [x] Decision, 2026-09-22: the env file is `.env`, as the clone (G2).
- [x] Decision, 2026-09-23: the writer agent ran on Opus 5.5 for one wave (`9ef9be8`), then went back to Sonnet by the user's decision the same day. The reviewer stays on Opus (`opus` resolves to `claude-opus-5-5` here, checked in the subagent logs).
- [x] Decision, 2026-09-23: the approval secret of `forge_approve_spec` and `forge_plan_app` moves from a module-level global in `server.py` to `AppResources.approval_secret`, minted in `app_lifespan` (Stage D group 8). Checked with a probe on FastMCP 4.0.2: over HTTP, stateless and stateful, three separate client sessions saw one lifespan entry and the same secret, so the guarantee stays one secret per server process. A second `AppResources` gets another secret, so its tokens are refused (fails closed). Not tested: several uvicorn workers (each worker has its own secret, as with the old global).

### P0

**G0. Baseline and gates**

- [x] `Makefile`: `test-live` runs all four live files (31 tests). The coverage comment says 90%. (`95c3b4c`)
- [x] `scripts/arch_scan.py`: eight scans, `--json`. `tests/test_arch_scan.py` proves each scan on the bad fixture and on the forms fixture, and ratchets the counts on `src/app`. Built in `95c3b4c`. The review found two scans that missed cases and rules that no test checked. Fixed in `aaff434`, which also adds `tests/fixtures/arch_scan_forms/`.
- [x] `tests/fixtures/tool_surface.json` frozen from `develop @ 9651283` (61 tools) (`95c3b4c`).
- [x] `tests/test_tool_surface_snapshot.py` takes its tool list from the fixture, so it cannot go silently empty when G12 empties `server.py` (review of G0, fixed in `aaff434`).
- [x] `tests/test_boilerplate_conformance.py` skips without `BOILERPLATE_DIR` and is red with it (expected). (`95c3b4c`)
- [x] Baseline: `make verify` 2,278 passed, 31 skipped.
- [x] Baseline: coverage 90.04%.
- [ ] Baseline: live, 31 tests green as the account. Attempt 1: 5 passed, 3 failed, 23 skipped. Attempt 2: 0 passed, 31 skipped. Blocked on the key pair (section 15).
- [x] Baseline: line count per file (Appendix C).
- [x] Baseline: the eight scan numbers (section 15). (`95c3b4c`)
- [ ] Reviewer: APPROVE. Round 1 found 7 findings, all fixed in `aaff434`. A re-review is pending.

**G1. The copied contracts**

- [x] `pyproject.toml` equals the clone except the listed deltas (`test_pyproject_equals_the_clone_except_deltas`). (`f3dee90`)
- [x] `line-length = 88`. The `E501` ratchet list is frozen in `tests/fixtures/e501_ratchet_g1.txt` and only shrinks. (`f3dee90`) 77 files at G1. `ruff format .` also reflows Python code fences inside `.md` files (ruff 0.16.7).
- [x] ty: 32 skips rewritten. `invalid-assignment` narrowed to four files. `root` keeps `"."` until G14. (`f3dee90`)
- [x] import-linter: the clone's three contracts, word for word. `make architecture` green. (`f3dee90`)
- [x] pytest `pythonpath = ["src"]`. `pytest-asyncio` in the dev group. (`f3dee90`)
- [x] `.claude/` and `.python-version` equal the clone except the listed deltas. (`f3dee90`)
- [x] Gate 2 (`make lint`) green. (`f3dee90`)
- [ ] Reviewer: APPROVE. Round 1 found 5 findings, all fixed in `23e5e18`. A re-review is pending.

### P1

**G2. Settings**

- [x] `infrastructure/config/settings.py`: frozen `Settings`, `load_settings()` with `load_dotenv()`. A missing key raises an error that names it. A domain without `dev-` is refused. (`a5bffb4`)
- [x] `KfConfig` takes its values from `Settings`. The `{prefix}` logic and the non-dev branch are gone. (`a5bffb4`)
- [x] `KF_DOMAIN`, `KF_ACCOUNT_ID`, `KF_ACCESS_KEY_ID`, `KF_ACCESS_KEY_SECRET` are gone from code and from `.env.example`. `kf.env.example` is folded into `.env.example`. (`a5bffb4`)
- [x] Scan `env_reads_outside_settings` = 0 (`8e2b4fc`). It was 1 until G9b removed the `KF_PROCESS_TEMPLATE` read in the domain.

**G3. Delete auth**

- [x] `auth.py` and `tests/test_oauth_per_user.py` deleted. The server has no auth provider. `import app.infrastructure.kissflow.auth` raises `ModuleNotFoundError`. (`30d8b75`)
- [x] `grep -rn "fastmcp.server.auth" src` is empty. `cryptography` pruned. (`30d8b75`) `starlette` and `mcp` also left `dependencies`: no module under `src/` imports them now.
- [x] `tests/test_proxy_headers.py` still green. (`30d8b75`)

**G4. The key pair from request headers**

- [x] `infrastructure/kissflow/credentials.py`: `KissflowKeyPair` with a masked `repr`. `caller_keys(settings)` reads the two headers over HTTP and `Settings` in stdio. A missing pair raises `ToolError`. (`04a8df3`)
- [x] The five TDD tests of G4 green. (`04a8df3`) Test 5 matches key-like names exactly, because `forge_plan_app` has an `approval_token` parameter that HR3 freezes.
- [x] `grep -rn "X-Access-Key-" src` shows only `credentials.py` and the adapters' signing. (`04a8df3`) Today the signing is `KfConfig.headers` in `client.py`. The adapters take it over in G8.

**G5. Lifespan and the pool**

- [x] `infrastructure/mcp/lifespan.py`: one `httpx.AsyncClient` with the `Settings` timeout, closed on exit. `AppResources` has one field per port and holds no credentials. (`7a988b7`) The context also carries `settings` (a delta: the tools need it for `caller_keys`). `HTTP_TIMEOUT_SECONDS=30` in `.env.example` and the Dockerfile keeps today's urllib timeout.

**P1 review, round 1 (`3172f93`)**

- [x] `.env.example` no longer turns its own comments into values (a copy of it started the server in HTTP mode with no auth after D1).
- [x] `KF_DEV_DOMAIN` must be a bare hostname, so `acme.kissflow.com/dev-` no longer passes the HR1 guard.
- [x] The transport refuses a redirect, so a 3xx cannot replay the key pair to another origin.
- [x] `KfConfig.key_secret` is masked, `scripts/deploy-wizard.sh` (`--allow-unauthenticated` with a false Entra claim) is deleted, and the Dockerfile header is corrected.
- [x] The "never logged" test now fails when the secret is logged, and one in-process test proves the headers reach the outbound request.
- [ ] Open, for G16: `docs/engine/13-deploying-the-mcp-server.md` still describes the deleted Entra and per-user OAuth flow.

**P1 gate**

- [ ] Gates 2 and 4 green. Gate 5 through stdio.

**Security review of Stage C (judge, round 1).** The two blocking findings were already fixed on the trunk by the P1 fixes (`3172f93`): the bare-hostname rule and the redirect refusal. Open, in a fix round: the first label must start with `dev-`, a runtime host and scheme check before every request, `expect_version=None` must not overwrite a versioned draft, error messages must not carry the host and account id, `httpx.InvalidURL` must be translated, a whitespace-only header must be refused, and caller ids must be percent-encoded in URL paths.

**Security review of the transport (judge, round 2, `564eac5`).** No reason to stop a dev-tenant release, under two conditions. (1) The hardening lives in the new adapters; the shipped server uses them only after Stage E switches `main.py` to `create_server()`, so no release note may claim it before then. (2) An id of exactly `..`, `.` or empty survives percent-encoding and httpx collapses the path, so `delete_page("APP", "..")` sends the delete-application request. That, the unencoded query values, the port and userinfo check, the host in transport errors, the trailing-newline hostname, and non-ASCII keys are a second fix round, before Stage E. Known residual: the read and the PUT in `read_verify_write` are two requests, so a concurrent write between them is not caught client-side; whether Kissflow rejects a stale `_meta_version` server-side is not tested.

**Transport hardening, round 2 (`0e733f2`).** `quote_path_segment` refuses `""`, `.` and `..` with no request sent (each proven case has a test). `build_query` encodes caller values in query strings (flow, app, dataset, copilot). `send_json` also refuses a port and userinfo. A transport error names only the exception class. The hostname rule uses `fullmatch`. `caller_keys` refuses a key that is not printable ASCII. `make verify` 3,266 passed after the merge. One test (a non-numeric port) passed before the fix too, because httpx already refused that URL; it stays as a guard on the new `.port` read. Judge re-check (2026-09-23): no blocking finding; all six claims hold on the wire, probed through `httpx.MockTransport` (`%2e%2e`, a slash, a backslash, U+FF0E, a port of `:443`, an empty userinfo, a trailing newline, a zero-width space: each refused or harmlessly encoded). Condition 1 of round 2 still stands until Stage E. Two nits go to a round 3: only the six proven sites have a refusal test (removing the guard from `get_flow_detail` or `archive_application` breaks no test), and `{kind}` in `flow.py` has no runtime guard (unreachable today, because every tool types `kind` as a `Literal`). Not taken: an id allowlist (the recorded ids fit `[A-Za-z0-9_-]+`, but live ids are not proven to) and a domain suffix pin (operator config). Not tested: whether Kissflow decodes `%2F` or `%252e` before routing.

**Transport hardening, round 3 (`28b419b`).** `tests/unit/infrastructure/kissflow/test_segment_guard.py` has one row per public method of the six adapters (48 rows, 49 guarded arguments, each tried with `..` and `""`: 98 refusal cases) and a completeness test, so a new adapter method without a row fails. Red proof on a scratch copy: with the guard removed from `get_flow_detail`, `..` reached the account-listing route. `_kind()` in `flow.py` refuses any flow kind outside the port's own `Literal` at all 10 sites (22 red cases, then green). `make verify` 3,709 passed.

### P2

**G6. Exceptions**

- [x] `application/exceptions.py`: the clone's three classes and the codes. (`898a6bc`)
- [ ] One test per mapping row. `ApplicationError` becomes `ToolError` at the tool edge. `mask_error_details is True`.
- [ ] `class Err` deleted. Scan `iserror_dicts` = 0. Every tool test asserts `ToolError` on failure.

**G9. Domain** (review round 1: the 88-column reflow glued words inside 13 refusal messages, a docstring was corrupted, `forge_create_flow` lost the `KF_PROCESS_TEMPLATE` path, private names leaked into caller-facing errors, and infrastructure read the entity's internal dict. Fixed in `45a40ac`: 13 messages restored with a test each, `nodes_of_kind`, `style_wire_value` and `field_mapping_index` made public, no `.nodes` read outside the domain, and `ShapeRefused` prints exactly the old text.)

- [x] `domain/entities/` (`FlowDraft`, `PageDraft`, `Navigation`), `domain/value_objects/`, `domain/exceptions.py` (`DomainError`). (`91a6f3b`, `096baa3`, `8e2b4fc`)
- [x] The rules of `verify.py` are `FlowDraft.problems()`. (`096baa3`)
- [x] `FlowDraft.from_wire(d).to_wire()` is byte-equal on every file in `tests/fixtures/*.json` and `shapes/*.json`. (`1873569`) 88 files per entity.
- [x] `DomainError` is raised on a `refuses-loudly` row. (`b8340f5`) `ShapeRefused(DomainError, ValueError)` keeps every message, so the old `pytest.raises(ValueError)` checks still hold.
- [x] The domain holds exactly `entities/`, `value_objects/`, `exceptions.py`, `__init__.py`. `graph.py:306` is gone. Scan `dict_draft_in_domain_api` = 0. (`8e2b4fc`) The template path now comes from `Settings`.

**G10. Models**

- [x] `AppSpec` is a Pydantic model in `models/requests/intake/app_spec.py`. (`1541fbe`) Every model uses `extra="forbid"`, because Pydantic drops an unknown key where `serde.py` raised.
- [x] `serde.py`, `tests/test_serde.py` and the `coerce_*` helpers deleted. Validation tests raise `ValidationError`. (`d258199`) `serde.py` and `tests/test_serde.py` are gone, with 12 golden files proving the dict shape did not change. The `coerce_*` helpers move with their families in Stage D.
- [ ] 61 request and response pairs, one class per file, each with its test.
- [ ] Surface snapshot equal.

### P3

**G7. Ports**

- [x] Seven ABCs: flow, app, page, dataset, item, copilot, docs. One fake per port in `tests/fakes/`. `test_ports.py` green. (`9b2a268`) 50 port methods. One test file per port module (the mirror rule) instead of one `test_ports.py`. The `port_methods_without_use_case` ceiling rose to 50 under the G7 exception; Stage D lowers it.

**G11. Use cases**
Progress: Stage D groups 1 (flow fields: `9d792ac`, `dcabfe5`) and 3 (flow workflow: `d1d59c4`) are merged, 11 of 61 tools. `make verify` 3,389 passed at `d1d59c4`. `port_methods_without_use_case` is 46. Group 2 (flow structure: `54b4a4f`, `e135c2f`, `bc175a8`) and group 9 (meta: `8c61450`) are merged too, 19 of 61 tools, `make verify` 3,787 passed. Group 5 (app roles and members: `f0f5e7e` to `a2d5082`) is merged with the shared conventions (tool-name file names, `Settings.resolve_app_id`, the `groups_note` key left out when empty as before, the old member-batch note text restored byte for byte, shared fakes in `tests/fakes/app_roles.py`), 27 of 61 tools, `make verify` 3,967 passed. `port_methods_without_use_case` is 34. Group 6 (app applications and reports: `25ef8b6` to `acbbf1b`) is merged, 33 of 61 tools, `make verify` 4,079 passed, `port_methods_without_use_case` 24. Its merge restored the old `grant_app_roles` note text byte for byte and moved its use cases to the one `_app_id.require_app_id`. `forge_sweep` stays read-only, as the old `run_sweep`; its `ok` is the old `isError` inverted, and an unknown scope is now a DTO `ValidationError`. Group 7 (page, dataset, item, copilot: `90ef4bc` to `446f03f`) is merged, 40 of 61 tools, `make verify` 4,357 passed, `port_methods_without_use_case` 8. Its merge removed an `ok` key from `forge_copilot_check` that the old dict never had (`ok = reply is not None` contradicted `reply_is_proof: False`), made `forge_dataset_records` leave out the per-op keys as the old dict did, restored two messages byte for byte, and put one empty-app helper in each of the page and copilot families. `forge_build_page` now dumps exactly the keys of the old report of the path it took (`steps` or `op`), through a wrap serializer (`2c06f8e`). A response with a wrap serializer gets the output schema `{"type": "object"}`, the same as the old `dict[str, Any]` tools. Group 4 (flow lifecycle: `4b25f93` to `f68ab8e`) is merged with the same conventions, 49 of 61 tools, `make verify` 4,540 passed. Its merge removed the `build_request` static methods, moved its rule-7 raises to `_fields.raise_if_write_failed` (which now takes a text `published` for a kind with no publish step), left `note` and `status` out when the old dict did, and moved its fakes to `tests/fakes/flow_lifecycle.py`. Kept decisions: a delete whose verifying re-list fails, and a publish whose status read-back fails, are VERIFY_FAILED. `port_methods_without_use_case` is 2: `AppRepository.archive_application` and `FlowRepository.archive_flow`. The old code called them only inside a delete, and the ports do that through `delete_*(archive_first=True)`. Open for G11: remove the two from the ports, the adapters and the fakes, or give them a use case. Groups 6, 7 and 8 and the fix round stopped at the usage limit on 2026-09-23 and were restarted from their saved worktree state. Group 8 (design and intake: `5adaac9` to `b4b2e36`, then the design stubs moved to `tests/fakes/design_stubs.py`) is merged. Stage D is complete: `create_server()` registers 61 tools, the same names as the old server, and each matches the frozen surface (input schema and docstring hash). `make verify` 4,977 passed, 41 skipped. Its merge ported the full-round `AppSpec` test, and a side-by-side run of the old and new render tools wrote byte-identical `out_dir` files. Review of groups 8 and 9 (2026-09-23): not approved, 5 required changes. The approval gate passed (mutation runs: a forced `compare_digest` fails 9 bypass tests; the token binds the same digest; only the lifespan secret reaches the use cases). Required: two `_field_spec_in` validators missing from the `kf_plan_field_change` DTO, five parallel-split compile tests not ported, the secret in `repr(AppResources)`, file writes in the application layer (moves to an `ArtifactWriter` port), and full key-set and error tests for the twelve tools. The fix round is merged (`28b873e` to `305b468`, `make verify` 5,008 passed): one shared `models/requests/_field_rules.py` for both field DTOs, `field(repr=False)` on the secret, an `ArtifactWriter` port with the `FileArtifactWriter` adapter (a side-by-side run of the old and new tools gave `diff -r` exit 0), and the missing tests. Incident during that round: the writer ran `git stash pop` in its worktree, which applied and dropped the user's parked stash (a `docs/brief.md` section). The main session put the original stash commit (`c38a4baa`) back with `git stash store` and its original message; its diff is identical. Rule 18 of the shared brief now forbids `git stash`. Review of groups 5, 6 and 7 (2026-09-23): not approved, 12 required changes. The worst: `forge_sweep` lost the no-app refusal, so with no app it read the list and flow routes without `_application_id` (a whole-account leak, CLAUDE.md); a doctor failure in `forge_create_template_app` escaped the cleanup and left a published app; failure messages dropped what had landed (a role-group write that emails the group, a created item's id, a page draft that a retry would duplicate). The page, dataset, item and copilot fix round is merged (`8046be0` to `7f678de`, `make verify` 5,046 passed): failure messages of `forge_simulate_case`, `forge_build_page` and `forge_set_navigation` name what landed (one `_write_fail.py` per family); the old `coerce_case_steps` / `coerce_page_steps` text is back and `"values": null` is accepted again; the read-back traps of `pages_live` are ported and proven by mutation; every tool pins its old success key set. Write-order exemptions, stated in the docstrings and tests: `forge_create_page` creates first (the old `create_page_flow` did, and nothing exists to read), and the dataset record writes have no read-back (the old `apply_dataset_records` had none). The app-family fix round is running. Review of the flow family (groups 2 and 4, and a re-check of the fix round of groups 1 and 3, 2026-09-23): not approved, 11 required changes. The worst: `forge_create_flow(kind="process")` stopped using `KF_PROCESS_TEMPLATE`, so it writes a different payload; `forge_create_list` can create a duplicate (the `Data` unwrap was dropped); a failed create hides the id it left on the tenant; tool tests survive the removal of `publish` and 20 other arguments. The earlier fix round: fixes 1 to 4, 7, 8, 10 and 11 landed and proven; 5 and 9 incomplete. A fix round is running. Decisions: (1) the four group 5 refusals renamed from `apply_*:` to `forge_*:` go back to the old text; lesson 5 covers only private names, and those functions were public (this reverses the instruction of the group 5 merge). (2) The embedded dicts of `forge_create_template_app` (`members`, `app_publish`, `doctor`) lose their `isError` keys with the top-level one; the facts stay in the other keys. (3) A create that did not read first in the old code, and the dataset record writes (no read-back in the old code), are exempt from the snapshot-first rule, stated in their docstrings and tests. (4) The `pyproject.toml` edits the reviewer flagged are the G0 and G1 decisions of 2026-09-22 (the clone's import-linter contracts, the E501 ratchet, the ty deltas). Decision: a malformed `spec` is refused with Pydantic's text for the request DTO (field paths `spec.<field>`), where the old text was `invalid spec: ... for AppSpec`. The fields and messages are the same; the prefix and the model name differ. Reviewer on groups 1 and 3 (2026-09-23): not approved, 11 required changes (a `parallel={}` refusal, lost failure data on destructive paths, changed refusal and payload text, lost `coerce_*` refusal text, tests that survive the mutation they should catch, missing tool tests for argument mapping and return shape, a domain bypass, and stale `_register_*` docstrings). The fix round is merged (`e531b1f`, `1ae05a7`, `ce09e4e`, `make verify` 4,130 passed). It also restored text the review had not named: four `resolve_event_triggers` messages (`—`, and `types.` module names), the bad-type refusal of `_field_spec_in.py`, and the blank-column refusal of `forge_add_table`. A follow-up (`b2df53c`) pins the old success key set of each of the 16 tools as a literal in its response test and its tool test; no DTO differed. `make verify` 4,558 passed. Decisions: `required` takes Pydantic's bool, so `"false"` now gives False (the old `bool("false")` gave True, a bug), and `null` still gives False; `forge_apply_layout` gets no position check on read-back until a live capture proves that Start and End read back unchanged (the old code had none either); `FlowDraft.set_required` replaces `graph.set_required` in one refusal (lesson 5). Merge note: group 3 resolved the app id as `app_id if app_id is not None else ...`, which keeps an empty `app_id`; the merge switched its five tools to `Settings.resolve_app_id`, the old rule `app_id or settings.kf_app or ""`.

- [ ] 61 use cases, one per tool, each with a happy-path test and a failure-code test.
- [ ] `use_cases/flow/_write_order.py`. Write-order invariant: the first port call of every write is `get_draft`, and the response carries `snapshot_version`. The write list is complete against the surface.
- [ ] Scan `port_methods_without_use_case` = 0.
- [ ] Gate 5.

### P4

**G8. Adapters**

- [x] Six httpx adapters and `_http.py` (`sign`, `translate`, the conflict rule). (`d44d205`) Every client and request sets `follow_redirects=False`.
- [x] Differential recordings per port method (old and new: method, URL, body). Error translation per status. The conflict test. The invariant transport on every adapter test. (`d44d205`, `a2ca377`) 48 recorded fixtures. The harness patches the P1 no-redirect opener, so the old-client side cannot pass with zero calls.
- [ ] `client.py`, `pages_live.py`, `dataplane.py` deleted. `grep -rn urllib src` is empty. Scan `adapter_methods_without_port` = 0.
- [ ] Coverage at 90 or above. Gate 5, run twice.

### P5

**G12. Thin tools and `create_server()`**

- [x] `create_server(lifespan)` registers nine tool modules. `main.py` wires `Settings` and the lifespan. (`2258926`)
- [x] Surface snapshot equal. `test_mcp_surface.py` and `test_tool_claims.py` green. The two G16 description changes and new hashes are in `27b92f5`.
- [x] Per family: argument mapping, `ApplicationError` to `ToolError`, no key pair gives `ToolError` before the use case. Stage D family tests and the Stage E combined gate passed.
- [x] Scans `tool_module_imports_own_family_only` = 0 and `module_level_fastmcp` = 0. `_client()` gone. (`c2e5cf7`, scan run 2026-09-23)

**G13. Playbook and capabilities**

- [x] `playbook.py` and `capabilities.py` implement `DocsReader`. The meta use cases depend on that port only. (`8c61450`, Stage D group 9) The reader returns plain data, runs off the event loop (`asyncio.to_thread`), and the old `search_capabilities` payload is rebuilt with the same keys in the same order. `tests_mirror_src` 16 to 14, `iserror_dicts` 75 to 74, `port_methods_without_use_case` 46 to 44.

**G14. Tests layout**

- [x] `tests/unit/` mirrors `src/app`. The live suites sit in `tests/integration/` with a README. `tests/conftest.py`. `src/__init__.py`. (`4cf4c38`)
- [x] Scan `tests_mirror_src` = 0. `make test-live` runs from the new path. The live run is red; this checks the path only.
- [x] The ty `root` delta is retired. (`4cf4c38`)

### P6

**G15. Docker and CI**

- [x] `make verify` is lint, then pytest with `--cov-fail-under=90`, as the clone. The CI `quality-gate` runs `make verify`. Local gate passed at 96.84%; GitLab pipeline not run. (`28e5992`, `6dc3dd9`)

**G16. Docs and ADR**

- [ ] `CLAUDE.md`, `code_architecture.md`, `docs/engine/13-deploying-the-mcp-server.md`, `docs/connect-claude-desktop.md`, `docs/demo-user-setup.md`, `docs/security-findings.md`, `.env.example`, `README.md`, `skills/kissflow-forge-builder/SKILL.md` updated.

- Progress: the non-skill docs were updated in `11f380c`; `.env.example` already matched the current settings. The vendored `SKILL.md` remains unread and unchanged because the user's standing HARD rule forbids reading a skill unless directly called. This checklist item stays open.

- [x] The two tool descriptions that cited deleted modules were corrected and `tests/fixtures/tool_surface.json` regenerated in the same commit. Names and input schemas stayed equal. (`27b92f5`)
- [x] `docs/adr/0007-boilerplate-architecture-and-connector-key-pair.md`. (`11f380c`)
- [x] `tests/test_engine_doc.py` and `tests/test_p0_scaffold.py` green (with the supplied transcript held outside the repo for the blindness scan).

### Big picture and gates

- [x] BP1: offline end to end (`tests/test_big_picture.py`), through `create_server()` and `httpx.MockTransport`. (`eef0f67`)
- [x] BP2: live end to end as the account. `make test-live` passed all 31 tests through the in-process MCP server on the dev tenant. A separate app-list check found zero temporary lifecycle, branching, or page apps after teardown. Docker and browser checks are separate.

- Failed live attempts remain recorded: the first temporary-app run had 5 passed, 23 skipped, 3 failed; the next had 23 passed, 8 failed; bare-process fixtures reached 26 passed, 5 failed; the doctor/page fix reached 27 passed, 4 failed; a premature probe item and wrong assignee shape caused 26 passed, 5 failed. The final run passed 31. The 403 `KISSFLOW_ERROR_050302` at Start was resolved by granting the calling user into the new AppRole after process publish.

- [x] BP3: conformance green (gate 1), ten checks passed after G14.
- [ ] Gates 1 to 5 green at the same time. The `E501` ratchet list is empty. Every ty delta is retired.

### Delivery (the user's goal, 2026-09-22)

- [x] The Docker image builds, and the MCP server runs in it (2026-09-23, fake env values, image built from `bc175a8`). Stdio: 61 tools listed, `kf_list_field_types` and `forge_playbook` answer. HTTP on `/mcp`: the same, and a live tool with no key headers fails with "no Kissflow key pair on this call"; with the two headers it passes the key check, and the fake secret is in no error and no log line. The Stage E image was rebuilt as `kissflow-forge:local`; its stdio MCP server listed 61 tools and returned a live `forge_sweep` for `N_A00`.
- [x] A new app was created on the dev tenant through the MCP server in Docker. The 2026-09-24 exercise created its own app, process and roles, then cleaned up the app after the run. A separate persistent template app and process remain on the tenant.
- [ ] Each of the 61 tools runs against that app through the MCP server in Docker. Round 5 logged 59 ok, 0 errors, and 2 intentional skips, and exited 0. `forge_copilot_check` needs a conversation id that the successful ask had not returned yet; `forge_share_report` needs a report id that this tool surface cannot create or discover. The exact per-tool result is in `artifacts/exercise-every-tool-round5-2026-09-24.json` (local artifact, not committed).
- [x] The steps to connect Claude Desktop to that server are written down: `docs/connect-claude-desktop.md` (stdio through `docker run`, and HTTP with the two headers). Not tested: Claude Desktop itself and the `mcp-remote` bridge.

## Appendix A. Tool to family, 61 tools


| Family      | Tools                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| flow (25)   | forge_add_field_validation, forge_add_goto_gate, forge_add_sequence_number, forge_add_table, forge_apply_fields, forge_apply_layout, forge_build_workflow, forge_create_flow, forge_create_list, forge_create_process, forge_delete_fields, forge_delete_flow, forge_doctor, forge_publish, forge_rename_fields, forge_set_branch_conditions, forge_set_events, forge_set_required, forge_set_styles, forge_set_visibility, kf_apply_field_change, kf_create_process, kf_get_flow_schema, kf_publish, kf_set_step_visibility |
| app (14)    | forge_add_member_roles, forge_add_role_users, forge_create_app, forge_create_app_role, forge_create_template_app, forge_delete_app_role, forge_grant_tier, forge_list_app_roles, forge_list_apps, forge_member_batch, forge_publish_app, forge_set_role_preference, forge_share_report, forge_sweep                                                                                                                                                                                                                          |
| page (3)    | forge_build_page, forge_create_page, forge_set_navigation                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| dataset (1) | forge_dataset_records                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| item (1)    | forge_simulate_case                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| copilot (2) | forge_copilot_ask, forge_copilot_check                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| intake (9)  | forge_apply_revisions, forge_approve_spec, forge_compare_to_spec, forge_intake_questions, forge_plan_app, forge_request_confirmation, forge_update_spec, kf_plan_field_change, kf_plan_step_visibility                                                                                                                                                                                                                                                                                                                       |
| design (3)  | forge_render_flow_diagram, forge_render_mockups, forge_render_schema_diagram                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| meta (3)    | forge_capabilities, forge_playbook, kf_list_field_types                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |


`forge_publish`, `forge_simulate_case` and `kf_get_flow_schema` reach two families. Their use case takes two ports. `forge_compare_to_spec` is spec-centric and takes the flow port.

## Appendix B. File map, today to target


| Today                                                                                                                     | Target                                                                                                            | Goal    |
| ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------- |
| `infrastructure/mcp/server.py`, 61 tools, 2,594 lines                                                                     | `infrastructure/mcp/server.py` with `create_server()` only. `infrastructure/mcp/tools/<family>.py`, nine modules. | G12     |
| `infrastructure/kissflow/client.py`, 6,582 lines, urllib                                                                  | `infrastructure/kissflow/<family>.py` (httpx) + `application/interfaces/<family>.py`, one pair per family         | G7, G8  |
| `infrastructure/kissflow/pages_live.py`                                                                                   | `infrastructure/kissflow/page.py`                                                                                 | G8      |
| `infrastructure/kissflow/dataplane.py`                                                                                    | `infrastructure/kissflow/item.py` + `application/interfaces/item.py`                                              | G7, G8  |
| `infrastructure/kissflow/auth.py`, 799 lines                                                                              | Deleted. The SRE gateway does it.                                                                                 | G3      |
| Env reads in 5 files                                                                                                      | `infrastructure/config/settings.py`                                                                               | G2      |
| `Err`, `client.py:113`                                                                                                    | `application/exceptions.py`                                                                                       | G6      |
| `main.py`, module-level `mcp`                                                                                             | `main.py` with `create_server()` and the lifespan                                                                 | G5, G12 |
| `domain/types.py`, `expr.py`                                                                                              | `domain/value_objects/`                                                                                           | G9      |
| `domain/graph.py`, `pages.py`, `nav.py`, `coverage.py`                                                                    | `domain/entities/`, `domain/value_objects/coverage.py`                                                            | G9      |
| `application/verify.py`, 816 lines                                                                                        | `domain/entities/flow_draft.py`, `problems()`                                                                     | G9      |
| `application/compare.py`, `engine.py`, `intake/compile.py`, `intake/questions.py`, `design/`, `querybank.py`, 5,740 lines | `application/use_cases/<family>/`                                                                                 | G11     |
| `application/intake/schema.py`, `intake/serde.py`, `tools.py` `coerce_*`                                                  | `application/models/requests/<family>/` and `models/responses/<family>/`. `serde.py` and `coerce_*` deleted.      | G10     |
| `infrastructure/capabilities.py`, `playbook.py`                                                                           | Adapters behind `application/interfaces/docs.py`                                                                  | G13     |
| `resources.py`                                                                                                            | Unchanged. The one filesystem anchor.                                                                             | none    |
| `tests/*.py`, 48 files, and `conftest.py`                                                                                 | `tests/unit/<path>/test_<module>.py`, `tests/integration/test_live_*.py`, `tests/conftest.py`                     | G14     |


## Appendix C. Line count per file, `develop @ 9651283`

Reported, never targeted (section 8). Counted with `git show 9651283:<path> | wc -l`.


| File                                            | Lines  |
| ----------------------------------------------- | ------ |
| `src/app/__init__.py`                           | 4      |
| `src/app/application/__init__.py`               | 2      |
| `src/app/application/compare.py`                | 503    |
| `src/app/application/design/__init__.py`        | 411    |
| `src/app/application/design/confirm.py`         | 705    |
| `src/app/application/design/diagram.py`         | 738    |
| `src/app/application/design/mockup.py`          | 681    |
| `src/app/application/engine.py`                 | 38     |
| `src/app/application/intake/__init__.py`        | 3      |
| `src/app/application/intake/compile.py`         | 1,718  |
| `src/app/application/intake/questions.py`       | 333    |
| `src/app/application/intake/schema.py`          | 799    |
| `src/app/application/intake/serde.py`           | 219    |
| `src/app/application/querybank.py`              | 613    |
| `src/app/application/tools.py`                  | 457    |
| `src/app/application/verify.py`                 | 816    |
| `src/app/domain/__init__.py`                    | 3      |
| `src/app/domain/coverage.py`                    | 309    |
| `src/app/domain/expr.py`                        | 470    |
| `src/app/domain/graph.py`                       | 3,040  |
| `src/app/domain/nav.py`                         | 121    |
| `src/app/domain/pages.py`                       | 919    |
| `src/app/domain/types.py`                       | 184    |
| `src/app/infrastructure/__init__.py`            | 2      |
| `src/app/infrastructure/capabilities.py`        | 119    |
| `src/app/infrastructure/kissflow/__init__.py`   | 1      |
| `src/app/infrastructure/kissflow/auth.py`       | 799    |
| `src/app/infrastructure/kissflow/client.py`     | 6,582  |
| `src/app/infrastructure/kissflow/dataplane.py`  | 675    |
| `src/app/infrastructure/kissflow/pages_live.py` | 844    |
| `src/app/infrastructure/mcp/__init__.py`        | 1      |
| `src/app/infrastructure/mcp/server.py`          | 2,594  |
| `src/app/infrastructure/playbook.py`            | 46     |
| `src/app/main.py`                               | 34     |
| `src/app/resources.py`                          | 30     |
| Total, 35 files                                 | 24,813 |
