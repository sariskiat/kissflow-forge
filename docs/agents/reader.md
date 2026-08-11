# Reader skill: two input files in, a filled spec out

Turn the two input files — a `.drawio` flow capture and an HTML page design — into
**spec JSON**, then hand that JSON to the engine through the surface that already
exists. The engine never learns to parse `.drawio` (decision D5, spec #29); this
skill is the only thing that reads the diagram, and it emits nothing the engine
can't already consume.

This is a **written, versioned, reviewable procedure** — not three subagents
hand-transcribing at ~370k tokens with no record of the rules used. Follow it in
order.

## The handoff surface (never invent a new one)

```
flow.drawio ─┐
             ├─► THIS SKILL ─► spec JSON ─► forge_update_spec ─► forge_request_confirmation
 design.html ┘                                                        │
                                                              forge_approve_spec  (human approves)
                                                                     │
                                                              forge_plan_app ─► BuildPlan
```

- `forge_update_spec(spec=None, patch=<spec JSON>)` merges your emitted dimensions
  onto a blank spec and re-validates through `spec_from_dict` — a bad key, wrong
  shape, or bad enum value is refused naming the exact path, never silently
  dropped. It also forces `approved: false`: emitting a spec is **not** approval.
- `forge_request_confirmation` → `forge_approve_spec` is the confirmation gate
  (ADR-0001, lint-not-lock). You never set `approved` yourself and it is not a
  legal patch key — a human approves the artifacts, then `forge_approve_spec`
  mints the only token `forge_plan_app` accepts.
- `forge_plan_app` compiles the approved, complete spec to its ordered BuildPlan.

The boundary is proven by the exact `spec_to_dict`/`spec_from_dict` round-trip
(`kfforge/intake/serde.py`) — `tests/test_reader_boundary.py` drives a synthetic
multi-split spec through this whole surface and asserts a real BuildPlan comes
back. Your job is to produce JSON that survives it.

## Token discipline — never open the XML whole

A `.drawio` is XML that costs ~126k tokens per ~800 lines read raw. **Never read
the whole file into context.** Analyze it with `python3` and pull out only the
structured facts the spec needs:

```bash
python3 - <<'PY'
import xml.etree.ElementTree as ET
root = ET.parse("flow.drawio").getroot()
# mxCell nodes: value (label), style, source/target (edges). Extract nodes + edges,
# print a compact summary — NEVER dump the raw XML back into the model's context.
for cell in root.iter("mxCell"):
    v = (cell.get("value") or "").strip()
    if v:
        print(cell.get("id"), "|", v)
PY
```

Same rule for the HTML design: parse for the fields, sections, and page widgets the
spec needs, not the whole document. The output of your parsing is a short structured
list you reason over, never the source bytes.

## Ask, don't enrich — mapped onto the existing gap split

When the diagram or mockup is **ambiguous or silent** on something the spec needs,
**surface it for a human decision. Never invent a value.** A skill that silently
fills a guess is worse than one that stops: a guessed routing literal or owner role
can make `compile` pass on a misread (see the consistent-lie risk below).

This is the **same blocking-vs-advisory split the human interview already uses** —
one rule, not a second mechanism:

- **Blocking gap** → *ask*. Every dimension except the advisory ones. `AppSpec`
  exposes `blocking_gaps()`; `forge_update_spec` echoes `blocking_gaps` on every
  call. A non-empty blocking gap means the reader must go back to the human (via
  `forge_intake_questions`) for that dimension — `forge_plan_app` refuses a spec
  with any blocking gap anyway.
- **Advisory gap** → *may proceed*. Only `ADVISORY_DIMENSIONS`
  (`kfforge/intake/schema.py` — currently dimension 9, timing). An empty advisory
  dimension does not block a plan; note it and move on.

The interview shrinks: it stops asking what the diagram already answers and asks
only the leftovers.

## Validate every routing literal against the LIVE word list

The sharpest failure: if you misread a Select's option once and write **both** the
option and the routing literal from that same misread, they agree with each other
and `compile._check_routing_literals`' own cross-check passes clean — a consistent
lie. The **only** defence is reading the option values off the live tenant, not off
the diagram.

- For each Select-backed decision field, read the field's real option values from
  its live list (`KfClient.get_list_items(<ReferredList id>)` — the same live read
  `forge_set_branch_conditions` already performs, which the offline build path never
  calls). Compare **byte-for-byte**: a wrong case or stray space writes fine,
  publishes fine, and the branch silently never fires (CLAUDE.md Expressions:
  "never guess a literal — read it").
- This read **must be in the plan**, not skipped because the offline cross-check is
  green. The cross-check only proves the option and the literal match *each other*;
  the live read is what proves they match *reality*.

⚠️ Tenant-state caveat: if the target app has no Kissflow List wired yet (KF_APP was
empty as of 2026-08-07), a Select-backed literal cannot be live-validated on that
tenant — surface that as a blocking gap (a human must wire the List), never proceed
on the diagram's spelling alone.

## Refuse any shape the coverage contract marks unbuildable — name the row

The coverage contract (`kfforge/coverage.py`, `ROWS`) is the single source of truth
for what a diagram may contain. Before emitting a spec, check every shape the
diagram uses against it. If a shape's row is **not** `captured-live` or `buildable`
— i.e. it is `refuses-loudly` — **stop and refuse, naming the row** (its stable
`key` and `reason`). Do not silently drop what you cannot express; a dropped shape
is invisible, a refusal is fixable.

The refusals you enforce at read time (each names its `coverage.get(<key>)` row):

| Diagram shape | Coverage row | Why refused |
|---|---|---|
| a split nested inside a branch | `nested-split` | no captured shape (THE RULE) |
| a jump from one branch into another | `cross-branch-jump` | no captured shape |
| the same step name in two branches | `duplicate-branch-step` | branch-id hash collision |
| a deciding value no branch claims | `unclaimed-value` | Fail-Open; item silently completes |
| a non-person step (auto/webhook/gate) | `auto-step` | no captured shape; no silent downgrade (D6) |
| a rich-text component | `rich-text-content` | serialization uncaptured (API-impossible) |
| a custom component | `custom-component` | no API install path (API-impossible) |
| a report widget / report | `report-creation` | no API path to create a report (API-impossible) |
| a word-list-backed dropdown (new) | `word-list-dropdown` | no build capability yet (#13) |

Most of these `compile` *also* refuses (the four routing shapes at compile, the
three API-impossible page widgets via `_check_no_api_impossible_widgets`) — refusing
at read time is the earlier, cheaper gate that names the row before a human ever
approves a spec that could never build. Role-scoped visibility (`role-scoped-
visibility`, #6) is the doctor's refusal, not yours (ADR-0003).

## What good output looks like

- A complete `AppSpec` JSON: every blocking dimension filled from the diagram/design
  or from an explicit human answer, no dimension guessed.
- Every routing literal byte-identical to a live option value.
- No `refuses-loudly` shape present — or the run stopped with a named-row refusal.
- Fully synthetic where it lands in this repo's tests (no target-domain names) — the
  case-1 golden and the built-app-vs-input diff belong to the eval harness (#28), not
  the forge, so the repo Blindness scan stays green.
