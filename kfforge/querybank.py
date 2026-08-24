"""Copilot query bank (map #42, ticket #44).

Programmatically enumerates the ~1000 copilot probe prompts the discovery
sweeps (#45-#52) consume, from the gather-list inventory: 28 process field
types (+ board-only Grid) x config tabs x modules, plus pages / navigation /
roles, plus semantic Q&A. Generic by construction — no tenant names; sweep
sessions substitute their own throwaway flow name into the ``{flow}``
placeholder.

Each query carries:
  - ``sweep``       which ticket consumes it (field-a/b/c, config-tabs,
                    boards, dataform, pages, roles, parity)
  - ``capability``  the docs/capabilities/ id the finding lands in
  - ``observable``  ``graph-diff`` (oracle = draft read-back diff, THE RULE)
                    or ``answer`` (oracle = copilot's reply text)
  - ``expect``      which graph subtree should change / what the answer feeds

CLI: ``python3 -m kfforge.querybank [--sweep S] [--observable O] [--count]``
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

GRAPH_DIFF = "graph-diff"
ANSWER = "answer"

MODULES: tuple[str, ...] = ("process", "board", "dataform")

SWEEPS: frozenset[str] = frozenset(
    {
        "field-a",  # 45
        "field-b",  # 46
        "field-c",  # 47
        "config-tabs",  # 48
        "boards",  # 49
        "dataform",  # 50
        "pages",  # 51
        "roles",  # 52
        "parity",  # engine already writes these; low-priority confirmation
    }
)


@dataclass(frozen=True)
class FieldType:
    name: str  # palette label, verbatim
    slug: str
    group: str  # basic | data-lookup | file-media | advanced | widget
    sweep: str  # which field sweep owns this type's capture
    modules: frozenset[str]  # palettes it appears in (dataform assumed = process; sweep verifies)
    no_event: bool = False  # builder offers no Event tab (CLAUDE.md: six types)


@dataclass(frozen=True)
class Query:
    id: str
    sweep: str
    module: str  # process | board | dataform | app (pages/nav/roles) | any (semantic)
    capability: str
    observable: str  # graph-diff | answer
    prompt: str
    expect: str


_ALL = frozenset(MODULES)
_NO_SEQ_NO_SMART = frozenset({"process", "dataform"})  # board palette lacks these (captured)
_BOARD_ONLY = frozenset({"board"})

# Palette captured 2026-08-12 from builder screenshots (gather-list images).
FIELD_TYPES: tuple[FieldType, ...] = (
    # engine-known types -> parity sweep
    FieldType("Text", "text", "basic", "parity", _ALL),
    FieldType("Number", "number", "basic", "parity", _ALL),
    FieldType("Date", "date", "basic", "parity", _ALL),
    FieldType("Dropdown", "dropdown", "basic", "parity", _ALL),
    FieldType("Yes/No", "yes-no", "basic", "parity", _ALL),
    FieldType("Text area", "text-area", "basic", "parity", _ALL),
    FieldType("Attachment", "attachment", "file-media", "parity", _ALL, no_event=True),
    FieldType("Sequence number", "sequence-number", "advanced", "parity", _NO_SEQ_NO_SMART, no_event=True),
    # sweep A (#45) — basic types
    FieldType("Date & Time", "date-time", "basic", "field-a", _ALL),
    FieldType("Multi-select dropdown", "multi-select-dropdown", "basic", "field-a", _ALL),
    FieldType("Currency", "currency", "basic", "field-a", _ALL),
    FieldType("Email", "email", "basic", "field-a", _ALL),
    FieldType("Checkbox", "checkbox", "basic", "field-a", _ALL),
    FieldType("Radio button", "radio-button", "basic", "field-a", _ALL),
    # sweep B (#46) — data lookup + media + User
    FieldType("Lookup", "lookup", "data-lookup", "field-b", _ALL),
    FieldType("Remote lookup", "remote-lookup", "data-lookup", "field-b", _ALL),
    FieldType("Image", "image", "file-media", "field-b", _ALL, no_event=True),
    FieldType("Smart attachment", "smart-attachment", "file-media", "field-b", _NO_SEQ_NO_SMART),
    FieldType("User", "user", "basic", "field-b", _ALL),
    # sweep C (#47) — advanced + widgets
    FieldType("Aggregation", "aggregation", "advanced", "field-c", _ALL),
    FieldType("Signature", "signature", "advanced", "field-c", _ALL, no_event=True),
    FieldType("Geolocation", "geolocation", "advanced", "field-c", _ALL, no_event=True),
    FieldType("Scanner", "scanner", "advanced", "field-c", _ALL),
    FieldType("Button", "button", "widget", "field-c", _ALL),
    FieldType("Slider", "slider", "widget", "field-c", _ALL),
    FieldType("Checklist", "checklist", "widget", "field-c", _ALL),
    FieldType("Rich text", "rich-text", "widget", "field-c", _ALL, no_event=True),
    FieldType("Rating", "rating", "widget", "field-c", _ALL),
    # board-only
    FieldType("Grid", "grid", "widget", "boards", _BOARD_ONLY),
)

# Config aspects, one per (tab x lever) from the builder's field panel.
# (aspect slug, tab, prompt template, expected graph subtree)
ASPECTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "required",
        "settings",
        'In {flow}, make the "{field}" field required.',
        "Required=true (or equivalent key) on the Field node",
    ),
    (
        "conditional-required",
        "settings",
        'In {flow}, make "{field}" required only when the "Priority Flag" Yes/No field is Yes.',
        "mark-as-required-when condition subtree referencing the deciding field",
    ),
    (
        "help-text",
        "settings",
        'In {flow}, set help text on "{field}" to "Fill this in carefully".',
        "help-text key on the Field node",
    ),
    (
        "default-value",
        "settings",
        'In {flow}, give "{field}" a sensible default value.',
        "DefaultValue key on the Field node (literal or formula — capture which)",
    ),
    (
        "computed",
        "settings",
        'In {flow}, make "{field}" a computed field derived from other fields.',
        "computed toggle + formula/expression subtree (or copilot refusal — capture it)",
    ),
    (
        "validation-rule",
        "validation",
        'In {flow}, add a validation rule to "{field}" so invalid values are rejected with a message.',
        "Validation rule subtree hung off the Field node",
    ),
    (
        "default-hidden",
        "visibility",
        'In {flow}, set the "{field}" field\'s default visibility to Hidden.',
        "default-visibility key/flag on the Field or its Column",
    ),
    (
        "visibility-rule",
        "visibility",
        'In {flow}, show "{field}" only when the "Priority Flag" Yes/No field is Yes.',
        "visibility rule condition subtree referencing the deciding field",
    ),
    (
        "appearance-rule",
        "style",
        'In {flow}, color "{field}" red when the "Priority Flag" Yes/No field is Yes.',
        "appearance-rule subtree (Style + condition) on the Field",
    ),
    (
        "event",
        "events",
        'In {flow}, add an event to "{field}" that updates another field when it changes.',
        "Event node + Field::Event back-reference, trigger string per source type",
    ),
)

# Page widget palette captured 2026-08-12 (gather-list images 12-14).
PAGE_WIDGETS: tuple[tuple[str, str], ...] = tuple(
    (label, label.lower().replace(" ", "-"))
    for label in (
        # general
        "Container", "Label", "Button", "Icon", "Divider", "Breadcrumb",
        "Card", "Progress bar", "Image", "Hyperlink", "Iframe", "Rich text",
        "Tab", "Master detail", "Popup", "Custom component",
        # views
        "Form", "Table", "Gallery", "Sheet", "Kanban", "Matrix", "List", "Timeline",
        # report
        "Report table", "Chart", "Report card", "Pivot", "Metrics",
    )
)

_VIEW_WIDGETS = frozenset({"form", "table", "gallery", "sheet", "kanban", "matrix", "list", "timeline"})
_REPORT_WIDGETS = frozenset({"report-table", "chart", "report-card", "pivot", "metrics"})

# Curated pairwise semantic diffs — the confusable choices an app designer faces.
PAIR_DIFFS: tuple[tuple[str, str], ...] = (
    ("Dropdown", "Radio button"),
    ("Dropdown", "Multi-select dropdown"),
    ("Checkbox", "Yes/No"),
    ("Checkbox", "Checklist"),
    ("Lookup", "Remote lookup"),
    ("Lookup", "Dropdown"),
    ("Attachment", "Smart attachment"),
    ("Attachment", "Image"),
    ("Text", "Text area"),
    ("Text area", "Rich text"),
    ("Number", "Currency"),
    ("Number", "Slider"),
    ("Date", "Date & Time"),
    ("Aggregation", "Number"),
    ("Scanner", "Text"),
)

_MODULE_FORM = {
    "process": "the {flow} process form",
    "board": "the {flow} board's item form",
    "dataform": "the {flow} dataform",
}

_CONFIG_SWEEP = {"process": "config-tabs", "board": "boards", "dataform": "dataform"}


def _field_queries() -> list[Query]:
    out: list[Query] = []
    for ft in FIELD_TYPES:
        for module in MODULES:
            if module not in ft.modules:
                continue
            where = _MODULE_FORM[module]
            fname = f"Probe {ft.name}"
            out.append(
                Query(
                    id=f"{module}.{ft.slug}.build",
                    sweep=ft.sweep if module == "process" else _CONFIG_SWEEP[module],
                    module=module,
                    capability=f"field.{ft.slug}",
                    observable=GRAPH_DIFF,
                    prompt=f'Add a {ft.name} field named "{fname}" to {where}.',
                    expect=f"new Field node (type {ft.name}) under the root Model, with its Row/Column placement and per-type keys",
                )
            )
            for aspect, tab, template, expect in ASPECTS:
                if aspect == "event" and ft.no_event:
                    continue
                out.append(
                    Query(
                        id=f"{module}.{ft.slug}.{aspect}",
                        sweep=_CONFIG_SWEEP[module],
                        module=module,
                        capability=f"field.{ft.slug}.{aspect}",
                        observable=GRAPH_DIFF,
                        prompt=template.format(flow="{flow}", field=fname),
                        expect=f"[{tab} tab] {expect}",
                    )
                )
        # semantic per type
        out.append(
            Query(
                id=f"semantic.{ft.slug}.when-to-use",
                sweep=ft.sweep,
                module="any",
                capability=f"field.{ft.slug}",
                observable=ANSWER,
                prompt=f"When should I use a {ft.name} field, and when is it the wrong choice?",
                expect="best-practice row: use cases + anti-patterns for the type",
            )
        )
        out.append(
            Query(
                id=f"semantic.{ft.slug}.module-choice",
                sweep=ft.sweep,
                module="any",
                capability=f"field.{ft.slug}",
                observable=ANSWER,
                prompt=f"Does a {ft.name} field behave differently in a process, a board, and a dataform? What changes?",
                expect="module-diffs row: per-module behavior/limit differences",
            )
        )
    return out


def _pair_diff_queries() -> list[Query]:
    slug = {ft.name: ft.slug for ft in FIELD_TYPES}
    return [
        Query(
            id=f"semantic.diff.{slug[a]}--{slug[b]}",
            sweep="config-tabs",
            module="any",
            capability=f"field.{slug[a]}",
            observable=ANSWER,
            prompt=f"What is the difference between a {a} field and a {b} field, and how do I pick?",
            expect="best-practice row: decision rule between the two types",
        )
        for a, b in PAIR_DIFFS
    ]


def _module_semantic_queries() -> list[Query]:
    items: tuple[tuple[str, str, str], ...] = (
        ("boards", "process-vs-board", "When should an app be a board instead of a process? Give the decision rule."),
        ("boards", "board-statuses", "How do board statuses and columns work, and how do items move between them?"),
        ("boards", "board-workflow", "Can a board have an approval workflow like a process? What are the limits?"),
        ("dataform", "process-vs-dataform", "When should data live in a dataform instead of process fields?"),
        ("dataform", "dataform-page-connection", "How do I connect a dataform to a process using a page, so process items can read and write dataform records?"),
        ("dataform", "dataform-views", "What view types can a dataform have, and who can edit records in each?"),
        ("dataform", "dataform-limits", "What limits or field behaviors are unique to dataforms?"),
        ("boards", "three-way", "I have a request-handling use case: how do I decide between process, board, and dataform?"),
    )
    return [
        Query(
            id=f"semantic.module.{slug}",
            sweep=sweep,
            module="any",
            capability=f"module.{slug}",
            observable=ANSWER,
            prompt=prompt,
            expect="module-diffs / best-practice row for module selection",
        )
        for sweep, slug, prompt in items
    ]


def _page_queries() -> list[Query]:
    out: list[Query] = []
    for label, slug in PAGE_WIDGETS:
        if slug in _VIEW_WIDGETS:
            bind = f" showing items from the {{flow}} process"
        elif slug in _REPORT_WIDGETS:
            bind = f" bound to a report over the {{flow}} process"
        else:
            bind = ""
        out.append(
            Query(
                id=f"page.{slug}.build",
                sweep="pages",
                module="app",
                capability=f"widget.{slug}",
                observable=GRAPH_DIFF,
                prompt=f"On the Probe Dashboard page, add a {label} widget{bind}.",
                expect="Component node + Script.web id + FieldMapping/Property wiring on the page draft",
            )
        )
        out.append(
            Query(
                id=f"page.{slug}.configure",
                sweep="pages",
                module="app",
                capability=f"widget.{slug}",
                observable=GRAPH_DIFF,
                prompt=f"On the Probe Dashboard page, configure the {label} widget: set its main options to non-default values.",
                expect="changed Property/FieldMapping/Style values on the Component",
            )
        )
        out.append(
            Query(
                id=f"page.{slug}.when-to-use",
                sweep="pages",
                module="any",
                capability=f"widget.{slug}",
                observable=ANSWER,
                prompt=f"When should I use the {label} page widget, and what does it need to work?",
                expect="best-practice row: use cases + required bindings",
            )
        )
    nav: tuple[tuple[str, str, str], ...] = (
        ("nav.create", "Create a second navigation set for external users.", "new Navigation node under the application draft"),
        ("nav.add-menu", "Add the Probe Dashboard page to the main navigation menu.", "Menu + FieldMapping + Property{Type:Page} chain"),
        ("nav.reorder", "Reorder the navigation so Probe Dashboard comes first.", "Menu order change in Navigation::Menu"),
        ("nav.default-page", "Make Probe Dashboard the app's default page.", "DefaultPage key on the application root"),
        ("nav.best-practice", "What are the best practices for structuring app navigation across roles?", "best-practice row for navigation"),
    )
    for slug, prompt, expect in nav:
        out.append(
            Query(
                id=f"page.{slug}",
                sweep="pages",
                module="app",
                capability=f"navigation.{slug.split('.', 1)[1]}",
                observable=ANSWER if slug == "nav.best-practice" else GRAPH_DIFF,
                prompt=prompt,
                expect=expect,
            )
        )
    return out


def _role_queries() -> list[Query]:
    out: list[Query] = []
    fixed: tuple[tuple[str, str, str, str], ...] = (
        ("create", "Create an app role called Probe Reviewer.", GRAPH_DIFF, "new AppRole record (account-level route; engine has no create path — prize capture)"),
        ("delete", "Delete the Probe Reviewer role.", GRAPH_DIFF, "AppRole removed from account-level list"),
        ("assign-user", "Add a user to the Probe Reviewer role.", GRAPH_DIFF, "Members list change on the AppRole detail"),
        ("default-page", "Set the Probe Reviewer role's default page to Probe Dashboard.", GRAPH_DIFF, "per-role default page binding on the application draft"),
        ("default-navigation", "Give the Probe Reviewer role its own navigation.", GRAPH_DIFF, "per-role Navigation binding"),
        ("view-permission", "Give Probe Reviewer read-only access to one view of {flow} only.", GRAPH_DIFF, "view-level permission entry"),
        ("report-permission", "Share the {flow} report with the Probe Reviewer role.", GRAPH_DIFF, "report member/batch entry"),
        ("tier-semantics", "What exactly can a role do at each permission level: No access, Read-only, Edit, Manage?", ANSWER, "best-practice row: the 4-tier permission matrix"),
        ("tier-by-module", "Do permission levels differ between processes, boards, and dataforms?", ANSWER, "module-diffs row: 2/4/3-level permission split"),
        ("role-best-practice", "What roles should a typical approval app define, and with which permissions?", ANSWER, "best-practice row for role design"),
    )
    for slug, prompt, observable, expect in fixed:
        out.append(
            Query(
                id=f"role.{slug}",
                sweep="roles",
                module="app",
                capability=f"role.{slug}",
                observable=observable,
                prompt=prompt,
                expect=expect,
            )
        )
    for module in MODULES:
        for tier in ("No access", "Read-only", "Edit", "Manage"):
            tslug = tier.lower().replace(" ", "-").replace("only", "only")
            out.append(
                Query(
                    id=f"role.tier.{module}.{tslug}",
                    sweep="roles",
                    module=module,
                    capability="role.permission-tier",
                    observable=GRAPH_DIFF,
                    prompt=f"Give the Probe Reviewer role {tier} permission on the {{flow}} {module}.",
                    expect="permission tier entry for the role on that flow (capture the wire shape per tier)",
                )
            )
    return out


def build_bank() -> list[Query]:
    bank = (
        _field_queries()
        + _pair_diff_queries()
        + _module_semantic_queries()
        + _page_queries()
        + _role_queries()
    )
    ids = [q.id for q in bank]
    assert len(ids) == len(set(ids)), "duplicate query ids"
    return bank


def _filter_sweep(bank: list[Query], sweep: str | None) -> list[Query]:
    if not sweep:
        return bank
    return [q for q in bank if q.sweep == sweep]


def _filter_observable(bank: list[Query], observable: str | None) -> list[Query]:
    if not observable:
        return bank
    return [q for q in bank if q.observable == observable]


def _print_counts(bank: list[Query]) -> None:
    counts: dict[str, int] = {}
    for q in bank:
        counts[q.sweep] = counts.get(q.sweep, 0) + 1
    for sweep in sorted(counts):
        print(f"{sweep}\t{counts[sweep]}")
    print(f"total\t{len(bank)}")


def _print_queries(bank: list[Query]) -> None:
    for q in bank:
        print(json.dumps(asdict(q), ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Copilot query bank (ticket #44)")
    ap.add_argument("--sweep", choices=sorted(SWEEPS))
    ap.add_argument("--observable", choices=[GRAPH_DIFF, ANSWER])
    ap.add_argument("--count", action="store_true", help="print per-sweep counts, not JSONL")
    args = ap.parse_args(argv)

    bank = build_bank()
    bank = _filter_sweep(bank, args.sweep)
    bank = _filter_observable(bank, args.observable)
    if args.count:
        _print_counts(bank)
        return 0

    _print_queries(bank)
    return 0


if __name__ == "__main__":
    sys.exit(main())
