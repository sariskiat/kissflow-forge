---
id: field.user
name: User field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > User"
shapes:
  - shapes/field_user.json
  - shapes/field_user_reference.json
params:
  - name: Field::QueryDefinition
    type: list
    required: true
    default: null
    constraints:
      - "the missing piece that CLAUDE.md said blocks publish — a child node with FlowType:\"User\""
      - "PROVEN live (issue #59): a real production process template with 3 such fields is PUBLISHED and renders (shapes/field_user_reference.json) — the earlier copilot capture (shapes/field_user.json) had the same shape but unverified publish; publish itself is no longer in doubt"
    depends_on: []
    status: proven-live
  - name: AutoFill
    type: boolean
    required: false
    default: false
    constraints:
      - "captured false on the original copilot capture; the 3 live production examples show both true (2 of 3) and no key at all (1 of 3) — absence is a real state, not implicit false, same pattern as Textarea AllowFormatting/Attachment CaptureOnly"
    depends_on: []
    status: captured
  - name: LHSModel
    type: string
    required: true
    default: null
    constraints:
      - "both \"User\" (account directory) and \"_employee\" (employee-record source) observed live across the 3 production examples — platform-level literals, pick per which directory the field should resolve against"
    depends_on: []
    status: proven-live
---

## What

Picks a Kissflow user, `Type:"User"`, with a `Field::QueryDefinition` child
(`FlowType:"User"`, `LHSModel:"User"|"_employee"`, `AutoFill`). Same
Reference/QueryDefinition family as Lookup and Remote lookup, differing only
in `FlowType`.

## Where

Form builder field palette ("User"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- **The former publish-blocker is corrected, not just captured.** CLAUDE.md
  used to say a User field's required shape was uncaptured and blocks publish
  outright. It is now PROVEN live: a real production process template
  carrying 3 User fields with this exact `Field::QueryDefinition` shape is
  published and renders (shapes/field_user_reference.json, issue #59) — not
  merely read off a copilot capture. A **bare** `Field{Type:"User"}` with no
  `Field::QueryDefinition` sibling still blocks publish; that half of the old
  belief stands.
- **Runtime binding on THIS engine's own dev tenant is still unverified** —
  the proof above is that the shape publishes and renders on the SOURCE prod
  tenant, not that dev has an equivalent `User`/`_employee` source to resolve
  against. Don't upgrade "publishes clean" to "usable end to end" without a
  live dev-tenant item walk through a User field (CLAUDE.md's own THE RULE).
- **Computed** — a User source is family-inferred to fire `onSelect`
  (`trigger_for`, CLAUDE.md #12), so a User pick can drive a computed field.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators for a User field are a config-tabs sweep (#48).

## Computed

No formula type. A User source drives a target via `forge_set_events`; trigger
family-inferred `onSelect`. Any field can be a computed target.

## Gotchas

`ValueType:"User"` assignees are ignored by the runtime (use AppRole) — that is
a workflow-assignee gotcha (CLAUDE.md Members first), separate from this User
FORM field. Do not conflate the two.
