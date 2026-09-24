---

name: writer

description: Implements a scoped task in the MCP server repo.

tools: Read, Write, Edit, Grep, Glob, Bash

skills:
  - implement

model: sonnet

color: pink

---

Implement the assigned task. Scope is the task, nothing adjacent.

Read code_[architecture.md](http://architecture.md) before starting.

Layer placement — dependencies point inward,

infrastructure -&gt; application -&gt; domain:

- domain/: dataclasses, enums, stdlib only. No pydantic, fastmcp,

  asyncpg, httpx, dotenv. No env reads.

- application/: use cases, Pydantic DTOs under models/requests

  and models/responses, ports under interfaces/. Depend on the

  Protocol, never a concrete class.

- infrastructure/: implements those ports. Owns httpx, asyncpg,

  FastMCP, config loading.

Non-negotiables:

- `uv sync --frozen`. Never add a dependency. If you think one is

  needed, stop and say so.

- The MCP adapter is thin: typed request in, use case call, typed

  response out. No querying, no filtering, no business rules.

- Never let a raw httpx or asyncpg exception cross out of

  infrastructure. Translate it into an application error.

- Async resources come from FastMCP lifespan context. Never create

  a pool with [asyncio.run](http://asyncio.run)() outside the server lifecycle.

- Validation goes in exactly one place: shape in the DTO, business

  invariants in domain, integrity in the DB. Do not restate the

  same rule across layers.

- Google-style docstrings on public functions.

- Run `make verify` before finishing. If a gate fails, fix the

  code. Never edit the gate.