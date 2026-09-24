# Add or change a forge_* tool

Read this when you add a tool, add a parameter, or change what a tool returns. The chain
below is the one `forge_playbook` uses; copy a sibling tool in the same family when in doubt.

## Files, inside out

| Layer | File | Notes |
|---|---|---|
| domain | `src/app/domain/value_objects/kinds.py` | Add a `Literal` alias for any closed set of values. The schema then shows an enum (`tests/test_mcp_boundary.py` checks this). |
| application | `src/app/application/models/requests/<family>/<tool>_request.py` | pydantic, `frozen=True`, `extra="forbid"`. Defaults keep old calls working. |
| application | `src/app/application/models/responses/<family>/<tool>_response.py` | Every counted bucket the tool reports is a field. |
| application | `src/app/application/interfaces/<port>.py` | Only if the tool needs a new port method. Abstract, documented `Raises:`. |
| application | `src/app/application/use_cases/<family>/<tool>.py` | One class, `execute(request) -> response`. Raises `ApplicationError` with a code. |
| infrastructure | `src/app/infrastructure/kissflow/<family>.py` or another adapter | Implements the port. Blocking I/O goes through `asyncio.to_thread`. |
| infrastructure | `src/app/infrastructure/mcp/tools/<family>.py` | Thin tool: arguments → request → `_shared.run_use_case(...)`. Pick the annotation profile in `_shared.py` from what the BODY does. `needs_kissflow=False` for offline tools. |
| infrastructure | `src/app/infrastructure/mcp/server.py` | `create_server()` calls each family's `register`. A new family needs a line here. |

The docstring is what a remote agent reads before it calls the tool. Say LIVE or OFFLINE, what
it writes, what it refuses, and the buckets it returns.

## Tests that move with a tool change

- Unit tests mirror the source path under `tests/unit/` (request model, response model, use
  case with a fake from `tests/fakes/`, adapter, tool module through an in-process client).
- `tests/fixtures/tool_surface.json`: regenerate with
  `uv run python tests/test_tool_surface_snapshot.py --write`, then read the diff. Only the
  tool you meant to change may move.
- `tests/test_mcp_boundary.py` `MINIMAL_ARGS`: one entry per tool; add the new tool.
- `tests/test_tool_claims.py`: every "is refused" sentence in a description needs a claim entry
  with arguments that trigger the refusal.
- `scripts/exercise_every_tool.py` and `tests/unit/scripts/test_exercise_every_tool.py`: the
  every-tool exerciser has a `_decide_<tool>` function and a canned response per tool.
- `tests/test_skill_tool_refs.py`: a renamed or removed tool must also leave the served skills.

## Check

```bash
uv run pytest -k <tool_name>
make verify
```

A new LIVE tool also needs one real call on the dev tenant, read back, before you call it done.
