---
id: page.design
name: Beautiful page design system (distilled from a live oracle page)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "App builder > Pages > page canvas (containers + widgets + Style)"
routes:
  - "GET /metadata/2/{acct}/application/{app}/page/{page_id}/draft"
shapes:
  - shapes/widget_view_form.json
params:
  - name: Style.Value
    type: object
    required: false
    default: null
    constraints:
      - "color keys take a token ref {ref:...} OR raw hex {value:'#RRGGBB'}; dimensions take raw CSS strings"
    depends_on: []
    status: captured
---

<!--
De-identified. Distilled 2026-08-13 from a live human-built page on the dev tenant
(34 components, 60 containers) that renders beautifully, diffed against the engine's
bare label+view/form build. The break that made pages ERROR (flow_type case) is fixed
separately (kfforge.pages._canon_config); THIS doc is about the design that makes a
RENDERING page look good instead of a skeleton. Real-tenant names never enter here.
-->

## What

A beautiful Kissflow page is a tree of styled `Container` nodes wrapping the
functional widgets — not a flat list of widgets. The engine's primitives
(`add_container`, `add_widget`, `set_styles`, `bind_widget`) can build every
shape below; the gap is DRIVING them with a design, not the primitives.

## Where

App builder page canvas. Each `Container` carries a `Style` node whose `Value`
holds CSS-shaped keys. A widget is a `Component` inside its own `Container`.

## Best practice

**The token palette (roles → captured reference values).** Swap the hex for a
brand's own; the ROLES and the spacing/radius scale are what generalize.

| Role | value |
|---|---|
| Page background | `#FCFAF2` (warm neutral) |
| Card background | `#FFFFFF` |
| Brand / hero background | `#2E6B3B` |
| Accent tint (chips) | `#EFF7F0` |
| Icon foreground / icon bg | `#2E6B3B` on `#DCEEE0` |
| Callout background | `#FBF3D3` |
| Body text / muted text | `#55564F` / `#7d7b73` |
| On-brand text | token `Color.White` |
| Title / body weight | token `Font.Weight.SemiBold` / `Font.Weight.Regular` |

**Scale.** Radius `14px` (cards, chips, tiles), `999px` (pills). Border `1px
solid`. Font `13px`. Spacing steps `4 / 10 / 12 / 16 / 20 / 24 / 28 / 32 px`.

**The reusable container recipes** (each a `Container` + `Style.Value`, children in `[]`):

- **Page shell** — `Container.Background=#FCFAF2`, vertical stack of cards, `Row.Gap` 16–20px.
- **Card** — `dir=column, gap=16px, pad=24–28px, bg=#FFFFFF, radius=14px`. One per page section.
- **Hero band** — a card but `bg=#2E6B3B, pad=32px`, text in `Color.White`: `[ row[ icon, column[ title, subtitle ] ], divider, row[ tip-chips… ], button ]`.
- **Section header** — `row gap=10–12px [ icon, label(SemiBold) ]`, or `column gap=4px [ title(SemiBold), subtitle(muted) ]`.
- **Tip chip** — `row gap=10px pad=14px bg=#EFF7F0 radius=14px [ icon, column[ label(SemiBold), label(muted) ] ]`.
- **Step tile** — `column gap=10px pad=20px bg=#FCFAF2 radius=14px [ step-pill, title, desc ]`; lay 3 across in a `row gap=16px`.
- **Step pill** — `row pad=4px bg=#2E6B3B radius=999px [ label("Step 1", Color.White) ]`.
- **Callout** — `row gap=10px pad=12px bg=#FBF3D3 radius=14px [ icon, label ]`.
- **Icon treatment** — `Icon.Color=#2E6B3B, Icon.Bg.Color=#DCEEE0`, small padding, rounded.

**Exact Style.Value keys** (write these, not CSS names): `Container.Flex.Direction`,
`Container.Width`, `Container.Height`, `Container.Flex.Wrap`, `Container.Row.Gap`,
`Container.Column.Gap`, `Container.Background`, `Container.Align.Items`,
`Container.Border.{Top,Right,Bottom,Left}.{Width}`, `Container.Border.Color`,
`Container.Border.Style`, `Container.Border.{Top,Bottom}.{Left,Right}.Radius`,
`Container.Padding.{Top,Right,Bottom,Left}`, `Label.Color`, `Label.Font.Size`,
`Label.Font.Weight`, `Label.Line.Height`, `Icon.Color`, `Icon.Bg.Color`,
`Icon.{Width,Height}`, `Icon.Padding.*`, `Divider.Color`, `Divider.Thickness`,
`Body.Container.*` (the page body), `Popup.*`.

## Gotchas

- A functional widget alone (a bare `view/form`) renders but looks like a
  skeleton — wrap it in a Card with a Section header above it.
- Color values accept BOTH `{ref:"Color.Xxx.Nnn"}` and `{value:"#RRGGBB"}` on a
  page (unlike form sections, which are token-only). A bogus token ref PUTs 200
  and fails silently at render — read a real token off the builder, never invent.
- `flow_type` is case-sensitive: `"Process"`, not `"process"` — the engine now
  canonicalizes this at write (kfforge.pages._canon_config), but it is the
  difference between a rendered widget and "Unable to display component".
