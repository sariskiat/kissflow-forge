# Known exclusions are owned by the judge, not the builder

The identical-rebuild diff lives in the judge repo, not the forge, per the
blindness split. The Known Exclusion list (role-scoped visibility, rich text
render, custom components, report creation) lives there too — outside the
builder's control — so the forge cannot reclassify its own defects as "platform
limits." This matches the project's integrity rule: the judge owns truth, the
builder is tested.

## Considered Options

- **Forge declares its own limits, judge reads them** — rejected: a forge bug
  reclassified as a "known limit" would be invisible.
- **Judge owns the list** — chosen.
