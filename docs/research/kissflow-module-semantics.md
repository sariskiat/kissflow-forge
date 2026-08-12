# Kissflow module semantics: Process vs Board vs Dataform

Research ticket: [#53](https://github.com/sariskiat/kissflow-forge/issues/53), part of map [#42](https://github.com/sariskiat/kissflow-forge/issues/42).

**Scope of this file (docs-research half only).** This captures what Kissflow's own
published documentation (Community help center, `helpdocs.kissflow.com`,
`kissflow.com` marketing/product pages) says about the three modules. A second
half — asking the Kissflow copilot directly, headless, and treating its answers
as `[copilot, unverified]` unless they match a doc citation or a live graph
capture — is **owed by a later session** and should be merged into this same
file when it lands. Nothing in this file was verified against a live graph
capture; every claim here is "the vendor says," not "the engine proved."

All fetches below were run 2026-08-12. Kissflow's help center has no visible
per-article revision date, so "as of 2026-08-12" is the freshness marker for
every citation, not a publish date on the source itself.

## 1. What each module is for, per the vendor

**Process** — a strict, sequential, form-driven workflow. Kissflow's own
definition: "a process is a type of workflow that ensures a strict sequential
set of steps performed on form data." An admin sets up a form, then "a
predefined path for it to follow, with the system automatically routing
requests through various steps until the item is complete."
[Process overview](https://community.kissflow.com/category/processes) (fetched 2026-08-12).
Processes are what this engine calls "flows" everywhere else in `CLAUDE.md` —
`ProcessDef`, `Activity`, `WorkflowType:"Sequence"`.

**Board** (the current, merged module — see the note on legacy Cases/Projects
below) — a customizable case-management / work-tracking system, explicitly
*not* limited to a strict linear path. Vendor framing: "With Kissflow Boards,
you can create highly adaptable workflows that let you keep track of
information and manage work efficiently." Boards let you "build custom
workflows to create, collaborate, and resolve items," offer three layouts
(Kanban, List, Matrix) to navigate items, and are positioned for "support
requests, project management, incident management, bug tracking, help desk,
sales pipeline, and HR help desk."
[Boards overview](https://community.kissflow.com/t/q6h9ql3/boards-overview) (fetched 2026-08-12).

**Dataform** — a pure data-collection form with **no workflow/approval step
at all**. Multiple pages converge on the same framing: "dataforms in Kissflow
apps are forms used for data-gathering and they do not include a workflow
approval process."
[Dataforms in apps category](https://community.kissflow.com/category/dataforms-in-apps) (fetched 2026-08-12);
[Creating and managing dataforms](https://community.kissflow.com/t/35yzjag/creating-and-managing-dataforms) (fetched 2026-08-12).
A dataform is scoped to Kissflow **Apps** specifically — it is the app-builder
sibling of the account-level Dataset (see §4).

**Vendor's own module inventory** (found while searching, not the primary
target page but directly relevant): "Kissflow includes three modules for
citizen developers (data forms, boards, and flows) and one module for IT teams
(apps)" — and separately, "Kissflow has five core modules to handle any type
of work that moves your way: processes, projects, cases, datasets, and
collaboration, although projects and cases are currently being merged into a
new module, boards." Source pages surfaced via WebSearch snippets citing
`community.kissflow.com`; I could not pin an exact single URL for the
"three modules for citizen developers" sentence — **mark that specific
sentence `[unverified — could not re-locate source URL]`**, everything else in
this paragraph is corroborated by the Boards-overview and Dataforms-category
pages already cited above.

## 2. Documented capability differences and constraints

### Workflow

- **Process**: one linear, admin-defined sequence of steps ("strict
  sequential set of steps"). No native Kanban/matrix view of items; the
  primary surfaces are the process dashboard and item detail.
  [Process overview](https://community.kissflow.com/category/processes) (fetched 2026-08-12).
- **Board**: "build custom workflows" with configurable custom statuses, plus
  three item-navigation layouts (Kanban / List / Matrix) rather than one
  fixed sequential view.
  [Boards overview](https://community.kissflow.com/t/q6h9ql3/boards-overview) (fetched 2026-08-12);
  [Using board layouts](https://community.kissflow.com/t/60h9qlm/using-board-layouts) (fetched 2026-08-12, title/topic only — not fetched in full).
- **Dataform**: no workflow engine at all — items are just submitted,
  updated, or deleted records, not steps in a routed sequence.
  [Creating and managing dataforms](https://community.kissflow.com/t/35yzjag/creating-and-managing-dataforms) (fetched 2026-08-12).

### Fields and soft limits

Documented **only for dataforms**, and worth recording verbatim since these
are hard, numeric constraints rather than qualitative description:

- Maximum 1,000 fields per dataform.
- Up to 10 child tables (default), 100 columns per child table (default),
  5,000 rows per child table maximum.
- 30 events per dataform (excluding button fields).
- 250-record display limit for checkbox/radio fields sourced from a dataform.

[Creating and managing dataforms](https://community.kissflow.com/t/35yzjag/creating-and-managing-dataforms) (fetched 2026-08-12).

No equivalent numeric soft-limit table was found published for Process or
Board fields — **`[unverified]`** whether the same or different caps apply
there; a search for "field types process form dataform board differences"
turned up only the shared field-type documentation (below), not per-module
numeric limits for Process/Board.

A separate field-count note applies across *all three* modules generically
(source did not scope it to one module): "only the following field types
support unique fields: Text, Number, Date, Dropdown, Email, Radio, and
Scanner," and "currency fields, rich text fields, grid fields, and button
fields... are not subject to soft limits in forms."
Search-result synthesis over
[Field types category](https://community.kissflow.com/category/field-types) (fetched 2026-08-12, title/topic only).

### Views

- **Dataform**: multiple documented visualization views beyond the base
  form — Data table view, Gallery view, Sheet view — each a separate
  configurable surface, and the Data table view specifically is what gets
  embedded into a page (see §5).
  [Dataforms in apps category](https://community.kissflow.com/category/dataforms-in-apps) (fetched 2026-08-12);
  [Data table view](https://community.kissflow.com/t/g9yzja2/data-table-view) (fetched 2026-08-12).
- **Board**: Kanban / List / Matrix layouts (see Workflow above), plus custom
  reports.
- **Process**: process dashboards ("actionable metrics to monitor how
  efficiently each process runs") and reports; no Kanban/matrix layout
  documented.
  [Process overview](https://community.kissflow.com/category/processes) (fetched 2026-08-12).

### Permissions — the sharpest, most concretely documented capability
### difference found in this pass

The three modules have **different-sized permission-level sets**, not just
different labels for the same levels:

| Module | Permission levels | Source |
|---|---|---|
| Process | **Initiate**, **Manage** (2 levels) | [Managing process roles and permissions](https://community.kissflow.com/t/83yzjcs/managing-process-roles-and-permissions) (fetched 2026-08-12) |
| Board | **Read-only**, **Initiate**, **Edit**, **Manage** (4 levels) | [Managing board roles and permissions](https://community.kissflow.com/t/m1yzjak/managing-board-roles-and-permissions) (fetched 2026-08-12) |
| Dataform | **Read-only**, **Edit**, **Manage** (3 levels) | [Managing dataform roles](https://community.kissflow.com/t/60yzja4/managing-dataform-roles) (fetched 2026-08-12) |

Verbatim level definitions:

- Process — Initiate: "Users will be able to initiate new process items. They
  can work on all of the items they have created and assigned to them."
  Manage: "Users will be able to create and manage process items. They will
  have default access to all reports."
- Board — Read-only: "allows a user to view items available in the system
  views, such as the All Items page, but the user cannot edit the data."
  Initiate: "allows a user to initiate new items in the board form and gives
  them the ability to work on all the items they have created." Edit: "Users
  can create board items. They can update all the items in the board, but
  can only delete the items created by themselves." Manage: "Users can create
  board items. They can update and delete all the items in the board. They
  can also create and access all board reports."
- Dataform — Read-only: "Users will be able to view the dataform." Edit:
  "Users will be able to view, create, and update the dataform... they cannot
  delete the dataform." Manage: "Users will be able to view, create, update,
  and delete the data in the dataform."

Why the shapes differ, read structurally rather than asserted by the vendor:
Process has no Read-only level because a process item that a user can only
view isn't really a workflow participant; Dataform has no Initiate level
because there's no workflow step to "initiate" into, only records to create.
This is `[inference from the documented level sets, not a vendor statement]`.

A shared rule across all three: **external app roles cannot be granted the
Manage permission**, on Process or Board (Dataform's own page didn't restate
this, but did not contradict it either — treat Dataform as
`[unverified]` on this specific point).
[Permissions](https://community.kissflow.com/t/83yzj9j/role-permissions) (fetched 2026-08-12, corroborated by the per-module pages above).

Permission inheritance is documented for both Process and Board: sharing a
process/board with a role auto-grants that role's users access to the
associated reports/views. [Boards overview](https://community.kissflow.com/t/q6h9ql3/boards-overview);
search-result synthesis, not independently re-verified by a direct fetch —
mark the inheritance claim `[unverified, secondary source]`.

## 3. Vendor best practices on when to pick which

Kissflow's own docs do **not** publish a single side-by-side "process vs
board vs dataform, pick one" decision page — I searched for it directly
("which module should I use," "process vs board vs dataform decision guide")
and found no such document. What exists instead is scattered positioning
language across product pages:

- **Case management framing for Boards**: "Enterprise Case Management (ECM)
  is a unified approach that helps organizations handle and resolve complex
  cases, incidents, or investigations more effectively," aimed at "incident
  management, claim processing, ticketing, bug tracking, service requests,
  and helpdesk work — situations with multiple interconnected tasks requiring
  tracking and collaboration."
  [Enterprise Case Management Software](https://kissflow.com/workflow/case) (fetched 2026-08-12).
- **Process framing**: positioned separately under "Process Transformation"
  and "Workflow Automation Platform" language, for "routine task automation"
  — sequential, repeatable operations rather than open-ended case handling.
  Same source as above; this is a synthesis across the page's sections, not
  one quoted sentence, so treat the framing (not the underlying page) as
  `[secondary synthesis]`.
- **Consolidation context, worth noting as background**: "Projects and case
  systems are currently being combined into a new module, boards. A case can
  be a bug, task, service request, or incident, depending on how you set up
  your board." This confirms Board is the *current* name for what used to be
  two separate modules (Projects, Cases) — a caller reading an older
  Kissflow doc or an older tenant's UI may still see "Case" or "Project"
  language for what is now Board.
  [Boards overview](https://community.kissflow.com/t/q6h9ql3/boards-overview) (fetched 2026-08-12).
- **Dataform framing**: consistently "for data-gathering... do not include a
  workflow approval process" — the implicit best practice is: pick Dataform
  when you need structured data capture with no approval/routing
  requirement, and reach for Process or Board the moment any step of "who
  looks at this next" needs to be enforced by the platform rather than left
  to the person entering data.

No vendor page was found that states an explicit rule like "use a board
when X, a process when Y" in a single sentence — the above is the closest
the documentation gets, assembled across pages. **This entire section should
be treated as the weakest-sourced part of this file** — it's positioning
language pulled from marketing/product pages, not a how-to guide, and it is
exactly the kind of question the copilot-Q&A half (owed, see top of file)
might answer more directly and concretely than the docs do.

## 4. Documented field-type / config differences between modules

- **Dropdown / multi-select / checkbox / radio option sourcing** differs by
  which module hosts the field:
  - In a normal Process or Board form: options come from a **List** (static,
    max 250 values, no filter conditions) or a **Dataset** (multi-row,
    multi-column, filterable, supports dependent dropdowns).
  - In an **App** (dataform context): options come from a **List** or a
    **Dataform** instead of a Dataset — "unlike a dataset used in the
    process, the data source in a dropdown field within an Application is a
    dataform."
  - Shared constraint regardless of source: for Checkbox and Radio fields,
    "only the first 250 values from the dataset or dataform will be
    displayed," while a Dropdown field can show the entire source.
  - Only Dropdown and Radio fields support dependent-dropdown chaining;
    Multi-select dropdown and Checkbox do not.
  [Selecting a data source for your dropdown field](https://community.kissflow.com/t/q6h4azg/selecting-a-data-source-for-dropdown-multi-select-dropdown-checkbox-and-radio-fields) (fetched 2026-08-12).
- **Custom form field components** are documented as addable to all three —
  "you can add custom form field components to dataforms, processes, or
  board forms" — i.e. this particular extensibility mechanism is *not*
  module-differentiated.
  [Working with custom form field components](https://community.kissflow.com/t/35yfjp0/working-with-custom-form-field-components) (fetched 2026-08-12, title/topic-level; full content not independently fetched — `[secondary, weak]`).
- **Field permissions in views** are a Dataform-specific, forthcoming/recent
  capability: "configuring field permissions in dataform views... manages
  which fields appear as editable, read-only, or hidden based on user
  roles." No equivalent "field permissions *in a view*" (as opposed to
  field-level Permission on the flow itself, which this engine already uses
  for Process — see `CLAUDE.md`'s Visibility section) was found documented
  for Board or Process.
  [Configuring field permissions in Dataform views](https://community.kissflow.com/t/83ykbq6/configuring-field-permissions-in-dataform-views) (fetched 2026-08-12, title/topic-level).
- No published per-module list of "this field type exists on Process but not
  Board" (or vice versa) was found. The one hard module-scoped rule
  discovered is the dropdown-source rule above (Dataset vs Dataform as the
  non-static source, keyed by which module hosts the field) — treat the
  absence of a broader field-type-availability table as a real documentation
  gap, not something this pass missed by not searching hard enough (three
  separate query phrasings turned up the same handful of pages).

## 5. How dataforms are typically connected to processes

Three distinct, separately documented mechanisms:

**(a) Lookup field.** The Lookup field lets one flow pull field values from
another flow to auto-populate a form. Configuration is: drag the Lookup field
onto the form → "Choose a flow to look up" (source can be a Process, Board,
Dataset, or Dataform — the "external data object" article states explicitly
that "the data is accessible to various modules in your app's data layer,
including Process, Boards, and Forms" and that the lookup "functions
identically to standard Process and Boards lookups using the Lookup field
component") → select which fields from the source are available → save.
**Constraint**: "only these fields will be available for lookup layout
configuration" — fields not selected at setup time cannot be added later
without reconfiguring the lookup from scratch.
[Lookup field overview](https://community.kissflow.com/t/g9h4azr/lookup-field) (fetched 2026-08-12);
[Lookup an external data object](https://community.kissflow.com/t/x2y3myx/lookup-an-external-data-object) (fetched 2026-08-12).

**(b) Remote lookup field.** A separate field type from (a) — pulls from
*external* (non-Kissflow) systems over HTTP, configured with an endpoint URL,
request type, and headers, response parsed as JSON/XML/text. Not itself a
dataform↔process connector, but documented alongside Lookup as the sibling
mechanism, and worth distinguishing so the two are never conflated: Lookup
crosses *Kissflow flows*, Remote lookup crosses *out of Kissflow entirely*.
"If another field depends on this Remote Lookup field, you cannot make
changes that could break that connection."
[Remote lookup field overview](https://community.kissflow.com/t/p8yx2qt/remote-lookup-field-overview) (fetched 2026-08-12).

**(c) Dataform connector, for outbound automation rather than inbound
lookup.** "App members can use the Dataform connector to send data from a
dataform to other flows in Kissflow or third-party apps." Three triggers:
item added, item updated, item deleted — each firing only on a **manual**
submit/edit/delete; bulk CSV import does **not** fire the connector ("the
integration will only fire for manual submissions; it will not be triggered
when data is uploaded in bulk using a CSV import"). Five supported actions:
create/submit, update fields, fetch one item, fetch multiple items, delete.
[Kissflow Dataform connector](https://community.kissflow.com/t/x2y35r7/connecting-to-kissflow-dataform) (fetched 2026-08-12).

**(d) Pages, via the Data table view.** A dataform's Data table view (one of
several dataform views, see §2) is the surface that gets embedded into an
app Page: "you can collect data using a dataform and then analyze it using a
data table view," and that view can then be "managed and used within a
page," including page-scoped quick filters that can be toggled on/off per
page. This is a **read/display** connection (dataform data surfaced inside a
page), distinct from (a)–(c) which are all form-to-form data-wiring
mechanisms.
[Data table view](https://community.kissflow.com/t/g9yzja2/data-table-view) (fetched 2026-08-12).

None of (a)–(d) is described by Kissflow as *the* canonical
dataform-to-process pattern — they read as four independent, composable
mechanisms rather than one blessed pipeline. This engine's own open question
("Dataform ↔ process connection via pages," logged in map #42's "Not yet
specified" section) is not resolved by the docs beyond confirming these four
named mechanisms exist; which combination a real build should use is still a
design decision for this engine, not something the vendor prescribes.

## 6. Confidence and gaps — what only live probing (or the copilot half) can answer

**High confidence (directly quoted from a fetched, named help-center page):**
- The three modules' basic definitions (§1).
- The Process/Board/Dataform permission-level sets and their definitions
  (§2, the sharpest finding in this pass).
- Dataform's numeric field/table/event soft limits (§2).
- The dropdown-source rule (Dataset for Process/Board vs Dataform for Apps)
  and the 250-value display cap (§4).
- The four dataform-connection mechanisms — Lookup, Remote lookup, Dataform
  connector, Data table view in a page (§5).

**Lower confidence (search-result synthesis, not independently re-fetched
from a primary page, or a page fetched only at title/topic level):**
- The "three modules for citizen developers" / "five core modules... project
  and cases merging into boards" framing (§1) — corroborated by the Boards
  overview page but the exact originating sentence's URL could not be
  re-located.
- Permission inheritance onto reports/views (§2).
- Custom-field-component parity across all three modules, and dataform
  view-level field permissions (§4) — both fetched only at title/topic
  granularity via WebFetch's category-page summarization, not the full
  article body.

**Real documentation gaps, not a search failure** — three separate query
phrasings converged on the same handful of pages each time:
- No published side-by-side "process vs board vs dataform" decision table
  or single best-practices page exists on Kissflow's own properties (§3).
- No published per-module field-type availability table (which field types
  exist on Process but not Board, etc.) beyond the one dropdown-source rule
  found (§4).
- No numeric soft-limit table for Process or Board fields, only for
  Dataform (§2).

**What this file cannot answer at all, by construction:**
- Whether any of the above documented behavior matches what this engine's
  own write API actually does — `CLAUDE.md`'s own THE RULE applies:
  "an HTTP 200 and a clean publish prove nothing." Every claim in this file
  is "the vendor's help center says," never "the engine proved against a
  live graph capture." Reconciling this against `shapes/` and a live probe
  is future work, not scoped to this ticket.
- The copilot-Q&A half of ticket #53 (owed — see the top of this file and
  the addendum comment on #53): what Kissflow's own AI assistant says when
  asked these same five questions directly, headless, treated as
  `[copilot, unverified]` unless it corroborates a doc citation here or a
  live graph capture elsewhere.
