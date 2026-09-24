## Pages

App-level artifacts live under a distinct flowtype: `application`. The
navigation chain is `GET/PUT /metadata/2/{acct}/application/{app_id}/draft` →
`Navigation` (one per role's menu set) → `Menu` → `FieldMapping` →
`Property{Type:"Page", Value:<page_id>}`. The application root also carries a
`DefaultPage`.

**Creating/deleting the APPLICATION itself (not a page within one) — captured
live 2026-08-06, node G's forge_create_app probe.** Tried the obvious shapes;
only ONE worked, ≤3 attempts:

```
POST   /flow/2/{acct}/application         {"Name": "..."}    -> 200 {_id, Type:"Application", Status:"Draft"}
GET    /flow/2/{acct}/application?page_size=100                -> the true inventory (mirrors the page-list route)
POST   /flow/2/{acct}/application/{id}/archive                 -> 200
DELETE /flow/2/{acct}/application/{id}                          -> 400 KISSFLOW_ERROR_04602 unless archived first
```
`POST /metadata/2/{acct}/application` and `POST /flow/2/{acct}/app` both 404
(wrong door). Same archive-then-delete rule as a process. Duplicate `Name` on
create 400s `KISSFLOW_ERROR_04204 FlowNameAlreadyExists`.

**An API-created application is born `Draft` and its Play/runtime view shows
"This app has not been published yet" until the APP-LEVEL publish fires**
(captured live 2026-08-12, browser round): `POST
/metadata/2/{acct}/application/{app}/publish` → 200 with a `Runtime_{app}`
blob. This is a separate step from per-flow and per-page publishes — build
order gains it as the app-shell finisher. ⚠️ Do NOT confuse it with the
builder's **Deploy** button, which is a CROSS-ENVIRONMENT promotion (dev →
UAT on this tenant, with Build/Version numbers) — never click Deploy on the
dev tenant. Builder URL pattern: `https://{domain}/appbuilder/{app_id}`
(Play/Studio; Studio sub-routes `/role/list`, `/process/{id}`, `/case/{id}`,
`/page/{id}`).

**No AppRole auto-provisions on a fresh application** — this used to be
inferred from a `PageAccess` list seen in one archive response;
independently re-tested and disproven live 2026-08-07 (node G review): a
throwaway app's own member roster (`GET .../application/{app}/member`) held
exactly one entry, the creating user, and zero AppRole entries. `member/batch` at the
application level 500s `FlowError` regardless of which AppRole name is tried
(`Admin`/`User`/`Member`), and a `ValueType:"User"` assignee persists and
publishes cleanly but never confers runtime submit permission —
`_current_context[0]` still lacks `_context_activity_instance_id` and submit
still returns `403 KISSFLOW_ERROR_050302`, even with that user granted via
`member/batch` (⚠️ `Permission` must be a **list**, e.g. `["Editable"]` — a
bare string 400s `KISSFLOW_ERROR_04231 UnsupportedPermissionError`).
⚠️ A CORRECTED BELIEF (2026-08-12, network capture by the user + live API
proof): adding a USER to an AppRole HAS an API route after all —
`PUT /app_role/2/{acct}/{role_id}?_application_id={app}` with the role
detail's keys plus **`"Users": [<assignee object>]`** — the WRITE key is
`Users`, the READ key is `Members` (asymmetric; a `Members` write 200s and is
silently ignored, which is what fooled every earlier probe). The assignee
object comes verbatim from `GET /user/2/{acct}/assignee?q=<name>` (`{_id,
Kind:"User", Email, Name}`); read back `Members`/`UserCount` to verify. An
API-created role has `Members: []` and its creator is NOT auto-added — a
step whose assignee role has no user members is what produces the 050302
submit-403. The workaround: grant membership at the PROCESS level
instead of the application level (`Role:"DataAdmin"`, `Permission:
["InitiateItems"]` — see Members first), and wire the assignee as
`ValueType:"AppRole"`, not `"User"`. Proven live end to end — a real item
walked from its start step through every user step to completion under
exactly that combination.

Each page is its own draft/publish unit:

```
GET/PUT /metadata/2/{acct}/application/{app}/page/{page_id}/draft
POST    /metadata/2/{acct}/application/{app}/page/{page_id}/publish     # page-level publish
```

**Page CRUD lives on a different surface than the draft:**
`GET /flow/2/{acct}/application/{app}/page` is the true inventory of live
pages — always page this with `?page_size=100`, the default page size is
small. `POST` the same path with `{"Name": "..."}` creates a virgin page (four
nodes: a `Page`, one `Container` of `Type:"Body"`, an empty `Style`, and a
`User`) — creating via the API does not touch navigation; a human still has
to add the Menu/FieldMapping/Property into whichever Navigation is currently
selected in the builder. `DELETE` on the same path returns a success response
for *any* id, including ids that were never real, and a deleted page's own
draft route keeps returning 200 afterward too (storage lingers) — **the page
LIST route is the only truth surface** for what pages actually exist; never
trust a delete response or a draft GET as proof either way.

The page graph itself is a Container/Component tree, plus supporting node
kinds:

- **Layout**: `Page` → a `Container` tree (`Type: Body|Container`, real flex
  layout values: direction, gap, padding).
- **Widgets** are `Component` nodes, identified by a `Script.web` string (see
  the palette below), configured through `FieldMapping`/`Property` pairs.
- **Styling**: `Style{Container|Component, Value:{"<key>":{...}}}`. Keys are
  CSS-shaped (background, text color, icon color, corner radii, per-side
  border widths). **Dimensional values are always raw CSS strings** — padding,
  gap, width, and radius keys hold literal strings like `"24px"`, `"100%"`,
  `"auto"`, on every page captured, no exceptions seen. **Color values accept
  two different shapes, and both render live**: raw hex as
  `{"value":"#RRGGBB"}` (122 instances, confined to the 2 pages this engine
  API-restyled directly) and design-token refs as `{"ref":"Color.Xxx.Nnn"}`
  (1394 instances, spread across the capture and dominant on 15 of the 17 pages
  — the platform's own assistant-built page alone accounts for 227 of them, and
  zero hex) — both proven rendering in the same 17-page capture. This is looser
  than form-section styling (see Node-graph invariants), where every captured
  example uses token refs and none has ever used raw hex; on a page, the two
  shapes coexist, even across sibling components. Token names are just as
  unvalidated on a page as on a form section — a bogus
  ref name PUTs 200 and fails silently at render (see Write path) — so when
  writing a ref, read the real name off the builder, never synthesize one. A
  freshly generated page has its layout values filled in but every color still
  at `{"value": None}`, which is the platform's own default look, not a broken
  style.
- **State and logic**: `Variable` (page-local state — plain text, JSON with a
  schema, or a list-of-objects shape good for KPI-tile data), `VariableRef`
  (a dot-path like `selectedItem.some_field` bound into a component's
  Property), `EventMapping` (an `on_click`-style hook on a Container, either
  a small JS action or a "open a popup" action), `Criteria`/`Condition`
  (per-container visibility driven off a page Variable — this is also how
  tabs are built: an "active tab" Variable plus a click handler that sets it,
  plus one Criteria per pane), `Popup` (its own Container subtree), and
  `Tabs`/`Tab` as a first-class widget.

**Widget binding is one of three trios**, and once you know which one a
widget uses, every widget of that family needs no further capture:

- View-type widgets (form, table, gallery, sheet, kanban, matrix, list,
  timeline, and the repeater mechanism) bind through
  `flow_type` / `flow_id` / `view_id`. A page-hosted `view/form` auto-creates
  a fresh Draft item every time it renders — expect draft-item count to climb
  just from testing.
- Report-type widgets (chart, table, card, pivot) bind through a single
  `report_id`, and simply render whatever visualization type that report
  already is — a card-type report renders as a card everywhere, a chart-type
  report as a chart everywhere.
- The native KPI-number widget binds through `metrics_type:"stepmetrics"` and
  needs only a flow id — it renders a full per-step analytics table (min/max/
  average time in step, sent-back and rejected counts, a duration filter)
  with zero other wiring required.
- General-purpose widgets (label, icon, button, divider, progress bar,
  breadcrumbs, card, image, hyperlink, rich text, iframe, tab, and a
  "master-detail" widget) mostly bind through a single relevant Property
  (a label's text lives in a `title` Property; a hyperlink needs
  `title`/`url`/`openInNewWindow`/`tooltip`; a button needs
  `caption`/`size`/`type`/`iconPosition`; an image needs `imageSrc`).

**The repeater mechanism**: write the host component's own FieldMapping trio
(`flow_type`/`flow_id`/a `view_id` such as the admin view/`view_type`/
`selectedFields`) and it renders as a live repeated row for each matching
record — but the row template's own labels only pick up per-row data when
their text Property is a `VariableRef` of `Type:"DatasourceParameter"`
pointing at something like `item.<field>`, and that VariableRef must also be
registered in the page's own `Page::VariableRef` list. Writing only the host
FieldMappings without registering the template's VariableRefs produces a
repeater that visibly repeats N times but shows no per-row data — that is the
template-binding step missing, not a broken repeater.

Known gaps, worth knowing before you spend time chasing them: ⚠️ rich-text
serialization is now CAPTURED (2026-08-12, #51 — replacing the old "not
captured" note): the `value` Property holds a PLAIN HTML STRING (`<h2>`,
`<p><strong>`, `<ul><li>`), no wrapper, survives publish byte-identical;
builder-UI pixel render still unchecked. A custom component needs an actual
installed component bundle, which has no API-driven install path at all
(re-confirmed #51: 4 route families 404, `/marketplace/2/{acct}/component`
503s — backend exists, nothing installed; manage surface is UI-only under
Developer > Custom Components); card- and pivot-type report widgets need a
matching report of that exact type to already exist; and a progress-bar
widget has been seen configured correctly yet render blank, cause unresolved
(a fresh #51 capture landed one cleanly — render check queued). Navigation
role-scoping: prefer `Menu.VisibleTo:[<role ids>]` on a shared Navigation
(no key = visible to all) over duplicating Menus per role — see
shapes/menu_navigation.json.

- **`Page::Component` registration is NOT load-bearing (#24, proven live
  2026-08-11).** `src/app/domain/pages.py` never writes `Page::Component`, so a
  built page leaves the key absent entirely. Test: built a page with three
  `general/label` widgets (their Component ids never registered, `Page::Component`
  absent), published, opened the builder — all three rendered fine. So an
  unregistered Component still renders; `add_widget` needs no registration step.
  A page's earlier partial registration (30 of 34) is therefore cosmetic, not
  a render gate. Recorded so nobody chases it again.
- **A freely-bound single live value on a page: the #23 Known Exclusion is
  NARROWED (2026-08-12, #51), not gone.** The old absolute ("no shape reaches
  it") fell to a live capture: a `VariableRef{Type:"PageVariable",
  Variable:"<pageVar>.<field>"}` bound into a label's text Property IS a
  real, reachable freely-bound live value — the working master-detail
  composition (repeater + `on_click` `setVariable("selectedItem", ...)` +
  Json-typed page `Variable` + one PageVariable ref per detail label, see
  shapes/variable_ref.json). What remains excluded: a live AGGREGATE number
  (an "open cases" count) with no user click feeding the Variable — the
  engine still has no route to a report of the right type, a `general/card`
  `count` is still a static int, and `metrics`/`stepmetrics` still renders a
  fixed per-step analytics TABLE only. So KPI tiles bound to a clicked
  record: buildable now; KPI tiles bound to a query aggregate: still refused
  at compile, metrics table is the substitute.

A few operational gotchas:

- Data-bound widgets obey a sticky **"Viewing as" role lens** in the builder —
  an access-denied message on a data widget usually means the role you're
  previewing as lacks permission on that flow or view, not that the page
  itself is broken. Check the lens before you go looking for a bug.
- Some auto-generated reference pages add an entirely NEW Navigation set
  instead of a Menu inside the role's existing navigation — the result is a
  page that was genuinely created but never actually appears as a tab
  anywhere a real user looks. If a newly built page "isn't showing up," check
  whether it landed in a stray Navigation before assuming the create failed.
  The fix for "give every role the same view" is to point every role's
  `Navigation::Menu` at the same shared Menu ids — the binding is what
  matters, not duplicating pages per role.
- Colors used **inside a Variable's own data** (for example, a KPI tile's
  color field in a list-of-objects Variable) are design-token references —
  the same convention most `Style.Value` colors use on a page. Token refs are
  the dominant color convention across the page capture; raw hex is the
  minority form, proven only on the pages this engine API-restyled directly.
- **Patching colors alone is not the same as achieving design parity with a
  mock.** If the mock has structural elements the current page doesn't — a
  hero band, a call-to-action, KPI tiles, status pills, a donut chart — no
  amount of recoloring existing containers closes that gap. Diff structure
  against the mock before claiming parity, not just style values.
- If you patch styles by matching on a container's name (a name-prefix rule,
  say), verify the match actually lands on a container that carries the
  style keys you're trying to set. A wrapper container one level up can share
  a very similar name while carrying none of the relevant keys, so the patch
  silently no-ops on exactly the containers you meant to hit.
