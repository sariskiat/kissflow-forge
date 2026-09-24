"""FlowDraft — the process/form/list node-graph, wrapped as a domain entity.

Invariant: for every JSON file `f` in `tests/fixtures/*.json` and
`shapes/*.json`, with `d = json.load(f)`:

    json.dumps(FlowDraft.from_wire(d).to_wire()) == json.dumps(d)

Round-tripping through this entity never reorders a key, drops a node, or
changes a value.

Every operation the former offline domain graph/expression modules and the
former application-layer health check used to perform on a raw dict is a
`FlowDraft` method here (G9b): each one pure, each one built from a deep
copy of `self`, so a `FlowDraft` never changes after it is built, and each
one returns a NEW `FlowDraft` (plus any extra value, when the old function
returned a tuple). The heavy lifting lives in two private modules this
class delegates to — `entities._flow_ops` (the node-graph mutators and
queries) and `entities._flow_rules` (the health-check rules) — so this
module stays a thin, readable facade. See CLAUDE.md's Node-graph
invariants, Workflow, Expressions, Gate polarity, Conditional routing,
Tables, Field events and Visibility sections
for the wire-shape rationale each method documents only in brief; the fuller
capture history lives on each private counterpart in `_flow_ops.py`.

A handful of names take no `FlowDraft` at all and stay module-level, exactly
as they were module-level functions before: `validate_layout_spans`,
`unbound_select`, `progressive_matrix`, `field_override_matrix`,
`nodes_of_kind`, `NO_PERMISSION_NODETYPES`, `ROW_UNITS`, `FIELD_SPAN`,
`SectionLayout`, and the type aliases `Step`, `Branch`, `ParallelSpec`,
`Matrix`.
"""

from __future__ import annotations

import copy
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self

from app.domain.entities._flow_ops import (
    FIELD_SPAN,
    NO_PERMISSION_NODETYPES,
    ROW_UNITS,
    Branch,
    Matrix,
    ParallelSpec,
    SectionLayout,
    Step,
    _add_field_validation,
    _add_goto_task,
    _add_sequence_number,
    _add_table,
    _apply_changes,
    _apply_exact_layout,
    _build_branch_condition,
    _build_goto_gate,
    _build_workflow,
    _clone_template_shell,
    _current_groups,
    _delete_closure,
    _delete_nodes,
    _ensure_process_def,
    _field_delete_blockers,
    _field_names,
    _field_override_matrix,
    _merge_groups,
    _parse_draft,
    _place_in_sections,
    _progressive_matrix,
    _regroup_into_sections,
    _remove_condition,
    _rename_fields,
    _repack_layout,
    _rewire_condition,
    _section_layout,
    _set_conditional_visibility,
    _set_field_computed,
    _set_field_events,
    _set_required,
    _set_section_style,
    _set_step_permissions,
    _transplant_template,
    nodes_of_kind,
    unbound_select,
    validate_layout_spans,
)
from app.domain.entities._flow_rules import DoctorReport, _problems
from app.domain.value_objects.field_spec import FieldSpec, ParsedField
from app.domain.value_objects.field_type import FieldType

__all__ = [
    "DoctorReport",
    "FIELD_SPAN",
    "NO_PERMISSION_NODETYPES",
    "ROW_UNITS",
    "Branch",
    "FlowDraft",
    "Matrix",
    "ParallelSpec",
    "SectionLayout",
    "Step",
    "field_override_matrix",
    "nodes_of_kind",
    "progressive_matrix",
    "unbound_select",
    "validate_layout_spans",
]


@dataclass(frozen=True)
class FlowDraft:
    """The normalized Kissflow process/form/list node-graph.

    Attributes:
        nodes: The wire-format node graph, keyed by node id.
    """

    nodes: dict[str, Any]

    @classmethod
    def from_wire(cls, wire: dict[str, Any]) -> Self:
        """Build a FlowDraft from a wire-format node graph.

        Args:
            wire: The raw node graph, as read from the Kissflow builder API
                or a JSON fixture. Deep-copied on the way in, so a mutation
                of `wire` after this call never reaches the entity.

        Returns:
            A new FlowDraft wrapping a deep copy of `wire`. No validation,
            no reordering.
        """
        return cls(nodes=copy.deepcopy(wire))

    def to_wire(self) -> dict[str, Any]:
        """Return the node graph in wire format.

        Returns:
            A deep copy of the stored node graph, safe for the caller to
            mutate without affecting this entity.
        """
        return copy.deepcopy(self.nodes)

    @property
    def version(self) -> str | None:
        """The draft's `_meta_version`, or None when the graph carries none."""
        return self.nodes.get("_meta_version")

    # ---------------------------------------------------------------------
    # Process scaffolding
    # ---------------------------------------------------------------------

    def ensure_process_def(
        self,
        steps: tuple[str, ...] = ("Submit",),
        assignee: tuple[str, str] | None = None,
    ) -> FlowDraft:
        """Give a bare PROCESS draft the workflow skeleton it needs to be writable at
        all.
        A freshly created process draft is only `{Root, Model}`; PUTting it back, even
        unmodified, 500s because the process metadata compiler requires a ProcessDef:
        `Start -> UserTask per step -> End`. No-op when this draft already has a
        `RootProcessDef`.

        Args:

            steps: The UserTask step names, in order.

            assignee: `(app_role_id, display_name)`, attached as a Resource

                on every step. Omitted, the steps have nobody to act on them.


        Returns:

            A new FlowDraft with the ProcessDef/Activity skeleton attached.


        Raises:

            ValueError: `steps` is empty.
        """
        return FlowDraft(nodes=_ensure_process_def(self.to_wire(), steps, assignee))

    def clone_template_shell(self, template_path: str | None = None) -> FlowDraft:
        """Graft the process-template identity shell onto a fresh process draft.

        Loads `shapes/process_template_identity_shell.json` (or
        `template_path`), a de-identified capture of a real production
        template: the identity/initiate field block, layout, the mandatory
        Model::Appearance/Style chain, a "Manager Approve" UserTask, and
        Button::Row. Every node is freshly re-minted, so two processes built
        this way never collide. No-op (returns an unchanged copy) when this
        draft already has a `RootProcessDef`.

        Args:
            template_path: A file path to a `shapes/*.json`-shaped capture.
                `None` means the shipped default shape.

        Returns:
            A new FlowDraft with the identity shell attached.

        Raises:
            ValueError: The template path does not resolve to a valid
                `shapes/*.json` shape.
        """
        return FlowDraft(nodes=_clone_template_shell(self.to_wire(), template_path))

    def transplant_template(
        self,
        *,
        app_role: tuple[str, str],
        template_path: str | pathlib.Path | None = None,
        force_ids: dict[str, str] | None = None,
    ) -> FlowDraft:
        """Graft the FULL de-identified production-template capture onto a bare draft.

        Unlike `clone_template_shell` (the small identity-shell scaffold),
        this carries the whole captured graph — every field, every
        branch/goto condition subtree — verbatim modulo a fresh id mapping,
        then repairs the root Appearance/Style chain the capture ships
        without, and re-points every workflow assignee at `app_role`.

        Args:
            app_role: `(app_role_id, display_name)` for the dev AppRole every
                UserTask's Resource is re-pointed at.
            template_path: A file path to the full capture. `None` means the
                shipped default (`shapes/process_template_full.json`).
            force_ids: `{old_id: new_id}` covering the template's own node
                ids; an id absent from it is minted fresh. Passing the same
                map twice reproduces byte-identical output only when the map
                is complete.

        Returns:
            A new FlowDraft with the full template grafted on.

        Raises:
            ValueError: This draft already has a `RootProcessDef`, the
                template path does not resolve, or the capture carries no
                Resource node to re-point.
        """
        return FlowDraft(
            nodes=_transplant_template(
                self.to_wire(),
                app_role=app_role,
                template_path=template_path,
                force_ids=force_ids,
            )
        )

    # ---------------------------------------------------------------------
    # Layout
    # ---------------------------------------------------------------------

    def regroup_into_sections(self, groups: list[tuple[str, list[str]]]) -> FlowDraft:
        """Rebuild the form layout so each named section holds the given fields, in
        order.
        Reuses the existing Field and Column nodes — only the Row/Section scaffolding
        above them is rebuilt. Fields not named in `groups` keep their order and land in
        a trailing section, so nothing is dropped.

        Args:

            groups: `[(section title, [field name, ...]), ...]`, in the

                order sections should appear. An empty field list creates a

                banner (header-only) section.


        Returns:

            A new FlowDraft with the rebuilt layout.


        Raises:

            ValueError: A field has no Column back-reference.
        """
        return FlowDraft(nodes=_regroup_into_sections(self.to_wire(), groups))

    def place_in_sections(self, groups: list[tuple[str, list[str]]]) -> FlowDraft:
        """Move the named fields into the named sections and change nothing else.

        The partial-layout edit `forge_apply_fields` uses: sections the caller does
        not name keep their exact subtree (Grids, Description, IsHidden, ids), a
        field already in its target section stays put, and a new title becomes a
        new Section at the end.

        Args:
            groups: `[(section title, [field name, ...]), ...]`.

        Returns:
            A new FlowDraft with only the named fields moved.
        """
        return FlowDraft(nodes=_place_in_sections(self.to_wire(), groups))

    def apply_exact_layout(
        self,
        layout: dict[str, list[list[tuple[str, int, int]]]],
        descriptions: dict[str, str] | None = None,
    ) -> FlowDraft:
        """Rebuild each named section's rows to an exact per-field grid layout.

        `layout` states `{section: [[(field name, Start, End), ...], ...]}`
        — one inner list per Row, top to bottom — and the engine places
        columns at exactly those grid coordinates. A field not named in its
        section's layout is left in place, in trailing rows, so nothing is
        ever silently dropped.

        Args:
            layout: The explicit per-section row/column placement.
            descriptions: Optional `{section: Description text}`, applied
                only to sections named in `layout`.

        Returns:
            A new FlowDraft with the rebuilt layout.

        Raises:
            ValueError: A span is off the 6-unit grid, two spans overlap, a
                field is placed twice, a named section does not exist, or a
                named field does not exist.
        """
        return FlowDraft(
            nodes=_apply_exact_layout(self.to_wire(), layout, descriptions)
        )

    def repack_layout(
        self,
        widths: dict[str, int] | None = None,
        section_descriptions: dict[str, str] | None = None,
        step_descriptions: dict[str, str] | None = None,
    ) -> FlowDraft:
        """Re-tile every section's fields at per-type widths, and add subtitles.

        Only Row nodes are rebuilt — Field/Column ids, per-step Permissions
        and Field::Event survive untouched. A row never exceeds the 6-unit
        grid.

        Args:
            widths: Per-field-type column width overrides, merged over the
                built-in defaults.
            section_descriptions: Optional `{section name: Description}`.
            step_descriptions: Optional `{step name: Description}`.

        Returns:
            A new FlowDraft with every section's rows re-tiled.
        """
        return FlowDraft(
            nodes=_repack_layout(
                self.to_wire(), widths, section_descriptions, step_descriptions
            )
        )

    def section_layout(self) -> SectionLayout:
        """Resolve the visibility fact base for this draft, once.

        Returns:
            The frozen `SectionLayout`: section-name resolution, column
            membership, and the no-Permission / table exclusions every
            visibility operation shares.
        """
        return _section_layout(self.nodes)

    def current_groups(self) -> list[tuple[str, list[str]]]:
        """The draft's current section -> [field name] layout, top to bottom.

        Root-model fields only; recurses through any nested wrapper Column
        (a template's Grid, or similar) so a field several layers deep is
        still found.

        Returns:
            `[(section title, [field name, ...]), ...]`, in display order.
        """
        return _current_groups(self.nodes)

    def merge_groups(
        self, groups: list[tuple[str, list[str]]]
    ) -> list[tuple[str, list[str]]]:
        """Overlay a caller's partial `groups` onto this draft's current section
        membership.
        Seeds the full map from `current_groups()` first, then moves only the fields the
        caller actually named — every other field keeps its current section. Feeds
        `regroup_into_sections`, so a partial `groups` never dumps every untouched field
        into "Other".

        Args:

            groups: The caller's partial section -> field-name overlay.


        Returns:

            The merged `[(section title, [field name, ...]), ...]`.
        """
        return _merge_groups(self.nodes, groups)

    # ---------------------------------------------------------------------
    # Fields
    # ---------------------------------------------------------------------

    def rename_fields(self, renames: dict[str, str]) -> FlowDraft:
        """Rename form fields, `{current name: new name}`.

        The node id is untouched, so per-step Permissions, Field::Event and
        any submitted data stay attached. Only root-model fields are
        renamed; child-table columns are left alone.

        Args:
            renames: `{current field name: new field name}`.

        Returns:
            A new FlowDraft with the fields renamed.

        Raises:
            ValueError: A name does not resolve to exactly one root field.
        """
        return FlowDraft(nodes=_rename_fields(self.to_wire(), renames))

    def set_required(self, required: set[str]) -> FlowDraft:
        """Set `Required` on root-model fields: True for `required`, False for the rest.

        Args:
            required: The field names that should be Required.

        Returns:
            A new FlowDraft with every root field's `Required` set.

        Raises:
            ValueError: `required` names a field that does not exist.
        """
        return FlowDraft(nodes=_set_required(self.to_wire(), required))

    def delete_closure(
        self, fields: tuple[str, ...] = (), tables: tuple[str, ...] = ()
    ) -> set[str]:
        """Every node id `delete_nodes` would remove for this request. Read-only.

        Args:
            fields: Field names to delete.
            tables: Table names to delete.

        Returns:
            The full doomed-node-id closure: the named nodes, everything
            they own (Permissions, Events, formula/validation/visibility
            clusters), and nothing else.

        Raises:
            ValueError: A name does not resolve.
        """
        return _delete_closure(self.nodes, fields, tables)

    def field_delete_blockers(
        self, fields: tuple[str, ...] = (), tables: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        """Every reference to a doomed node that a surviving node still holds.
        Read-only.

        Args:

            fields: Field names that would be deleted.

            tables: Table names that would be deleted.


        Returns:

            One human-readable sentence per blocker, naming the remedy.

            Empty means the delete is clean.


        Raises:

            ValueError: A name does not resolve.
        """
        return _field_delete_blockers(self.nodes, fields, tables)

    def delete_nodes(
        self, fields: tuple[str, ...] = (), tables: tuple[str, ...] = ()
    ) -> FlowDraft:
        """Delete form fields and/or child tables by name, with every back-reference
        swept.
        Does not check whether a SURVIVING node still points at what it just deleted —
        that audit is `field_delete_blockers`.

        Args:

            fields: Field names to delete.

            tables: Table names to delete.


        Returns:

            A new FlowDraft with the named nodes and their owned clusters

            removed, and every dangling list reference swept.


        Raises:

            ValueError: A name does not resolve.
        """
        return FlowDraft(nodes=_delete_nodes(self.to_wire(), fields, tables))

    def field_names(self) -> set[str]:
        """Names of every existing Field node — the basis for idempotent reconcile.

        Returns:
            Every Field node's `Name`, root and table children alike.
        """
        return _field_names(self.nodes)

    def parse_draft(self) -> list[ParsedField]:
        """Extract every Field node from the graph.

        Returns:
            One `ParsedField` per Field node.

        Raises:
            ValueError: A field's `Type` is outside the closed `FieldType` enum.
        """
        return _parse_draft(self.nodes)

    def apply_changes(self, changes: list[FieldSpec]) -> FlowDraft:
        """Return a new FlowDraft with the field changes applied.

        MVP: only ADD new fields (`field_id=None`); a name already present
        is skipped (idempotent reconcile). Invalid field types, and an
        unbound Select, are rejected before any graph mutation.

        Args:
            changes: The field specs to add.

        Returns:
            A new FlowDraft with the new fields wired in.

        Raises:
            ValueError: A spec names an unbound Select.
            NotImplementedError: A spec carries a `field_id` (edit, not MVP).
        """
        return FlowDraft(nodes=_apply_changes(self.to_wire(), changes))

    # ---------------------------------------------------------------------
    # Tables and computed content
    # ---------------------------------------------------------------------

    def add_table(
        self,
        name: str,
        columns: Sequence[
            tuple[str, FieldType | str]
            | tuple[str, FieldType | str, dict[str, Any] | None]
        ],
        max_rows: int | None = None,
        allow_import: bool = False,
        after_section: str | None = None,
    ) -> FlowDraft:
        """Add a child table. No-op if a table of that name already exists.

        A table is a `Column{Type:"Model"}` hosting a nested Model, in its
        own root-level Row — never nested in a Section.

        Args:
            name: The table's name.
            columns: `(name, type)` or `(name, type, options)` per column. A
                child Select must name its `ReferredList` in `options`.
            max_rows: Writes `MaxRow`, Kissflow's native row cap.
            allow_import: Writes `AllowImport` on the host column.
            after_section: A Section name whose root row the host row must
                land directly after. `None` appends last.

        Returns:
            A new FlowDraft with the table attached.

        Raises:
            ValueError: A column is Type Select with no `ReferredList`, or
                `after_section` names a Section with no root row.
        """
        return FlowDraft(
            nodes=_add_table(
                self.to_wire(), name, columns, max_rows, allow_import, after_section
            )
        )

    def add_sequence_number(
        self,
        field_name: str,
        section_name: str,
        prefix: str,
        padding: str,
        step_activity_name: str,
        start: int = 0,
        end: int = FIELD_SPAN,
    ) -> FlowDraft:
        """Add an auto-numbered item-id field, in its own hidden row at a section's end.

        No-op if a SequenceNumber field of that name already exists. Call
        this after the section's layout is already placed — the new row is
        appended.

        Args:
            field_name: The new field's name.
            section_name: The section to append the hidden row to.
            prefix: The literal prefix concatenated ahead of the number.
            padding: The zero-padding pattern (e.g. `"0001"`).
            step_activity_name: The workflow step name the Step property
                stamps at.
            start: The hidden column's grid Start.
            end: The hidden column's grid End.

        Returns:
            A new FlowDraft with the SequenceNumber field attached.

        Raises:
            ValueError: `section_name` or `step_activity_name` does not
                resolve.
        """
        return FlowDraft(
            nodes=_add_sequence_number(
                self.to_wire(),
                field_name,
                section_name,
                prefix,
                padding,
                step_activity_name,
                start,
                end,
            )
        )

    def add_field_validation(
        self,
        field_name: str,
        operator: str,
        value: str,
        rhs_type: str = "Value",
        error_message: str | None = None,
    ) -> FlowDraft:
        """Attach a per-field validation rule. Idempotent on `(field_name, operator,
        value)`.

        Args:

            field_name: The field the rule guards.

            operator: The wire operator string (e.g. `"CONTAINS"`, `"MAX_LENGTH"`).

            value: The literal RHS value.

            rhs_type: The RHS wire type.

            error_message: The Condition's human-readable failure text.


        Returns:

            A new FlowDraft with the validation Condition attached.


        Raises:

            ValueError: `field_name` does not resolve.
        """
        return FlowDraft(
            nodes=_add_field_validation(
                self.to_wire(), field_name, operator, value, rhs_type, error_message
            )
        )

    def set_field_computed(self, field_name: str, formula: dict[str, Any]) -> FlowDraft:
        """Attach a computed-field formula. Idempotent: replaces any existing one.

        Args:
            field_name: The field to compute.
            formula: `{"fn": ..., "args": [...], "data_type": <optional>}`,
                a small function-call AST. Each arg is `{"field": name}`,
                `{"static": literal}`, or a nested `{"fn": ..., "args": [...]}`.

        Returns:
            A new FlowDraft with the computed formula attached.

        Raises:
            ValueError: `field_name` does not resolve, `formula` is
                malformed, or an arg's `field` reference does not resolve.
        """
        return FlowDraft(nodes=_set_field_computed(self.to_wire(), field_name, formula))

    def set_conditional_visibility(
        self,
        field_name: str,
        trigger_field_name: str,
        operator: str,
        rhs: str,
    ) -> FlowDraft:
        """Attach form-level conditional visibility. Idempotent per target field.

        Args:
            field_name: The field whose column is conditionally hidden.
            trigger_field_name: The field whose value gates it.
            operator: The wire comparison operator.
            rhs: The literal compared against the trigger's value.

        Returns:
            A new FlowDraft with the ColumnVisibility rule attached.

        Raises:
            ValueError: Either field name does not resolve to a valid Column.
        """
        return FlowDraft(
            nodes=_set_conditional_visibility(
                self.to_wire(), field_name, trigger_field_name, operator, rhs
            )
        )

    def set_field_events(self, events: dict[str, list[tuple[str, str]]]) -> FlowDraft:
        """Attach SDK events to fields. Replaces every existing event on the named
        fields.

        Args:

            events: `{field name: [(trigger, script), ...]}`.


        Returns:

            A new FlowDraft with the events attached.


        Raises:

            ValueError: A field name does not resolve, a script uses

                `KFSDK` (undefined at runtime — use the injected `kf`), a

                script has a top-level `await`, or a script references a

                field id not present in this draft.
        """
        return FlowDraft(nodes=_set_field_events(self.to_wire(), events))

    def set_section_style(
        self,
        styles: dict[str, dict[str, Any]],
        root_style: dict[str, Any] | None = None,
        hint_text_position: str | None = None,
    ) -> FlowDraft:
        """Colour sections and, optionally, the root Model's own Appearance/Style chain.

        Idempotent: an existing Appearance/Style pair is reused, never
        duplicated.

        Args:
            styles: `{section name: {property: token or None}}`. `None`
                removes a property (back to the theme default).
            root_style: The same shape, applied to the root Model's chain.
            hint_text_position: Sets `HintTextPosition` on the root
                Appearance node.

        Returns:
            A new FlowDraft with the styles attached.

        Raises:
            ValueError: A section name does not resolve, or a dict style
                value uses a key other than `ref`/`value`.
        """
        return FlowDraft(
            nodes=_set_section_style(
                self.to_wire(), styles, root_style, hint_text_position
            )
        )

    # ---------------------------------------------------------------------
    # Workflow
    # ---------------------------------------------------------------------

    def build_workflow(
        self,
        steps: list[Step],
        parallel: ParallelSpec | None = None,
        parallel_after: int | None = None,
        roles: dict[str, str] | None = None,
        step_meta: dict[str, dict[str, Any]] | None = None,
        parallels: list[tuple[ParallelSpec, int]] | None = None,
    ) -> FlowDraft:
        """Replace the whole workflow: Start -> steps -> [Parallel branches]* -> ... ->
        End.
        Destructive: every existing Activity/ProcessDef/Resource is replaced, so
        per-step Permission nodes that referenced them are dropped too — snapshot before
        calling.

        Args:

            steps: `[(step name, app-role id or None), ...]`.

            parallel: A single `(name, branches)` gateway to insert.

            parallel_after: The 0-indexed position into `steps` the single

                `parallel` gateway follows.

            roles: `{role id: display name}`, used to label each step's

                assignee Resource.

            step_meta: `{step name: {"suspended": bool, "description": str}}`.

            parallels: `[(parallel_spec, after_index), ...]` for N sequential

                gateways. Mutually exclusive with `parallel`/`parallel_after`.


        Returns:

            A new FlowDraft with the rebuilt workflow.


        Raises:

            ValueError: Both `parallels` and `parallel` are given, or two

                branches (even across different gateways) share a name.
        """
        return FlowDraft(
            nodes=_build_workflow(
                self.to_wire(),
                steps,
                parallel,
                parallel_after,
                roles,
                step_meta,
                parallels,
            )
        )

    def add_goto_task(
        self,
        *,
        target_activity_id: str,
        name: str | None = None,
        branch_process_def_id: str | None = None,
    ) -> tuple[FlowDraft, str]:
        """Add a GotoTask: a backward-jump edge node targeting `target_activity_id`.

        Carries no condition of its own and no Permission — pair with
        `build_goto_gate` to add the Boolean loop condition, or the Goto
        loops forever. Idempotent: re-running with the same target reuses
        the same deterministic id.

        Args:
            target_activity_id: The Activity to jump back to.
            name: Defaults to `"Goto-<target activity name>"`.
            branch_process_def_id: Pins and validates which branch's chain
                hosts the new GotoTask — the target must already belong to
                it. Omit for the default (derive the chain from the
                target's own ProcessDef).

        Returns:
            `(new FlowDraft, new GotoTask activity id)`.

        Raises:
            ValueError: `target_activity_id` is not a real Activity, that
                Activity has no valid `ProcessDef` back-reference, or
                `branch_process_def_id` is given but invalid or mismatched.
        """
        nodes, goto_id = _add_goto_task(
            self.to_wire(),
            target_activity_id=target_activity_id,
            name=name,
            branch_process_def_id=branch_process_def_id,
        )
        return FlowDraft(nodes=nodes), goto_id

    def set_step_permissions(
        self, matrix: Matrix, field_matrix: Matrix | None = None
    ) -> FlowDraft:
        """Rebuild the per-step Permission matrix from scratch.

        Existing Permission nodes are deleted rather than merged, so a
        leftover node never silently keeps an old visibility.

        Args:
            matrix: Section name -> activity id -> Visibility. Every
                field column must be covered by exactly one section (or by
                `field_matrix`), or the call is refused.
            field_matrix: Field name -> activity id -> Visibility, for
                per-field overrides layered on top of `matrix`.

        Returns:
            A new FlowDraft with the Permission matrix rebuilt.

        Raises:
            ValueError: `matrix`/`field_matrix` names a section, field or
                no-Permission column it cannot target, or a field column is
                covered by no matrix row at all.
        """
        return FlowDraft(
            nodes=_set_step_permissions(self.to_wire(), matrix, field_matrix)
        )

    # ---------------------------------------------------------------------
    # Branch and goto conditions
    # ---------------------------------------------------------------------

    def build_branch_condition(
        self,
        *,
        process_def_id: str,
        field_id: str,
        literal: str,
        options: list[str] | None,
    ) -> FlowDraft:
        """Attach a ProcessDef-owned branch condition: `<field> = "<literal>"`.

        `options`, when given, is validated before any mutation — a literal
        that cannot match a real list option is never written.

        Args:
            process_def_id: The branch's ProcessDef.
            field_id: The deciding field.
            literal: The value the field is compared against.
            options: The field's real option values, or `None` to skip
                validation (the caller owns the risk).

        Returns:
            A new FlowDraft with the branch condition attached.

        Raises:
            ValueError: `process_def_id`/`field_id` does not resolve, the
                field's type has no captured wire DataType for a string
                comparison, or `options` is given and `literal` is not in it.
        """
        return FlowDraft(
            nodes=_build_branch_condition(
                self.to_wire(),
                process_def_id=process_def_id,
                field_id=field_id,
                literal=literal,
                options=options,
            )
        )

    def process_def_expression_ids(self, process_def_id: str) -> tuple[str, ...]:
        """The Expression ids a ProcessDef already carries as branch conditions.

        Read-only node-graph reasoning a caller needs before rebuilding a
        branch condition (list the existing ones, `remove_condition` each,
        then attach the new one) without reaching into the entity's own
        internal dict to walk `ProcessDef::Expression` itself.

        Args:
            process_def_id: The ProcessDef node's id. An id with no matching
                node, or one carrying no `ProcessDef::Expression` back-ref,
                both read as "no existing conditions".

        Returns:
            The ProcessDef's `ProcessDef::Expression` ids, in wire order.
        """
        node = self.nodes.get(process_def_id) or {}
        return tuple(node.get("ProcessDef::Expression") or ())

    def remove_condition(self, *, expression_id: str) -> FlowDraft:
        """Delete a branch or goto condition — the Expression, its whole Node AST, and
        every `Field::Node` back-ref it left behind.

        Args:
            expression_id: The Expression node to remove.

        Returns:
            A new FlowDraft with the condition removed.

        Raises:
            ValueError: `expression_id` does not resolve, or it is
                Property-owned (a value-generator prefix, not a condition).
        """
        return FlowDraft(
            nodes=_remove_condition(self.to_wire(), expression_id=expression_id)
        )

    def build_goto_gate(self, *, goto_activity_id: str, field_id: str) -> FlowDraft:
        """Attach an Activity-owned loop condition to a GotoTask: `<field> = false()`.

        Gate polarity: only a Boolean may gate a loop — an unticked Boolean
        fails closed, while a blank Select would fail open.

        Args:
            goto_activity_id: The GotoTask Activity to gate.
            field_id: The Boolean field the loop condition tests.

        Returns:
            A new FlowDraft with the loop condition attached.

        Raises:
            ValueError: `goto_activity_id`/`field_id` does not resolve, or
                the field's Type is not `"Boolean"`.
        """
        return FlowDraft(
            nodes=_build_goto_gate(
                self.to_wire(), goto_activity_id=goto_activity_id, field_id=field_id
            )
        )

    def rewire_condition(
        self,
        *,
        expression_id: str,
        new_field_id: str,
        options: list[str] | None = None,
        new_literal: str | None = None,
    ) -> FlowDraft:
        """Repoint an existing branch or goto condition at a different field.

        The condition's owner (branch vs goto) does not change; only the
        field under test does. Six edits happen together, or none do: the
        Field node's reference and DataType, the literal node, the root's
        Category, the ExpressionStr mirror, and the `Field::Node` back-ref.

        Args:
            expression_id: The condition to rewire.
            new_field_id: The field to point it at.
            options: For a branch condition, the new field's real option
                values (validated the same way `build_branch_condition` does).
            new_literal: For a branch condition, the new literal. Omitted,
                the existing Static value carries over. Must be omitted for
                a goto condition (always tested against `false()`).

        Returns:
            A new FlowDraft with the condition rewired.

        Raises:
            ValueError: Either id does not resolve, the condition AST is
                malformed, the condition is Property-owned, the owner/
                field-type pairing is invalid, `new_literal` is given on a
                goto rewire, or an omitted `new_literal` has nothing
                sensible to carry over.
        """
        return FlowDraft(
            nodes=_rewire_condition(
                self.to_wire(),
                expression_id=expression_id,
                new_field_id=new_field_id,
                options=options,
                new_literal=new_literal,
            )
        )

    # ---------------------------------------------------------------------
    # Health check
    # ---------------------------------------------------------------------

    def problems(
        self,
        *,
        list_options: dict[str, list[str]] | None = None,
        visibility_role_claims: tuple[str, ...] | list[str] = (),
    ) -> DoctorReport:
        """Audit this draft graph offline. Read-only: never mutates.

        Every reference that would break the form at load, leave a branch
        or loop silently misconfigured, or leave a section nobody can ever
        edit.

        Args:
            list_options: `{Kissflow list id: its live legal option
                values}`. A branch literal is checked against real options
                only when its list id is a key here; every other literal is
                recorded in `unvalidated`.
            visibility_role_claims: The spec's role-scoped visibility
                claims, one sentence each — always a problem, since a
                Permission node is (column, step), never (column, role).

        Returns:
            The `DoctorReport`: `problems`, per-rule `checked` counts,
            `unvalidated` branch literals, and an `unvalidatable_scripts`
            count.

        Raises:
            ValueError: This draft has no valid `Root` key.
        """
        return _problems(
            self.nodes,
            list_options=list_options,
            visibility_role_claims=visibility_role_claims,
        )


def progressive_matrix(flow: FlowDraft, owners: dict[str, list[str]]) -> Matrix:
    """Section-by-step visibility: show a section at the step that owns it, and only
    there.
    A section with no owner comes out ReadOnly everywhere rather than being dropped.

    Args:

        flow: The FlowDraft to read the workflow and sections from.

        owners: Section NAME -> the workflow step names that own it.


    Returns:

        A step-visibility Matrix: section name -> activity id -> Visibility.


    Raises:

        ValueError: `owners` names a section or a step that does not

            resolve against `flow`, or an activity sits outside the

            workflow chain.
    """
    return _progressive_matrix(flow.nodes, owners)


def field_override_matrix(
    flow: FlowDraft, field_owners: dict[str, list[str]]
) -> Matrix:
    """Per-field editable-step matrix, the field-level lever `progressive_matrix` cannot
    express.

    Args:

        flow: The FlowDraft to read the workflow from.

        field_owners: Field NAME -> the workflow step names where it is

            Editable.


    Returns:

        A step-visibility Matrix: field name -> activity id -> Visibility.


    Raises:

        ValueError: `field_owners` names a step that does not resolve

            against `flow`, or an activity sits outside the workflow chain.
    """
    return _field_override_matrix(flow.nodes, field_owners)
