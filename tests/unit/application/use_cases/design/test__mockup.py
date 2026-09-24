"""Spec for app.application.use_cases.design._mockup: the self-contained HTML
mockups.

Ported verbatim from `tests/test_design.py` (its mockup.py section), Stage D
group 8. Every assertion is unchanged; only the import path moved.
"""

from __future__ import annotations

import dataclasses
import html
import re
import xml.etree.ElementTree as ET

from tests.fakes.design_stubs import (
    Field,
    Page,
    Personas,
    PersonaView,
    VisibilityEntry,
    VisibilityMatrix,
    _assert_no_external_refs,
    _assert_well_formed_html,
    _card_slice,
    _field_slice,
    _marker_slice,
    bare_shape_spec,
    sample_spec,
)

from app.application.use_cases.design._diagram import (
    schema_diagram_xml,
)
from app.application.use_cases.design._mockup import (
    _format_sequence,
    design_bundle_html,
    form_mockups_html,
    persona_pages_html,
)

# --------------------------------------------------------------------------------------
# mockup.py -- faithfulness (visibility, computed fields, sections, types, terminal
# states, sequence) plus the round-1 coverage (off-spine fields, select options, master
# data, process summary, widgets, no-external-refs).
# --------------------------------------------------------------------------------------


class TestFormMockups:
    def test_well_formed_and_no_external_refs(self):
        doc = form_mockups_html(sample_spec())
        _assert_well_formed_html(doc)
        _assert_no_external_refs(doc)

    def test_bare_sequence_shape_also_works(self):
        doc = form_mockups_html(bare_shape_spec())
        _assert_well_formed_html(doc)

    def test_every_field_of_a_stage_appears_scoped_to_its_card(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        intake_slice = _card_slice(doc, "Intake")
        for f in spec.data_model.fields:
            if f.stage == "Intake":
                assert f.name in intake_slice
        foreign = next(f for f in spec.data_model.fields if f.stage != "Intake")
        assert foreign.name not in intake_slice

    def test_off_spine_field_is_rendered_not_silently_dropped(self):
        """
        Major 3 (round 1): "Rejection Reason" lives on "Closed - Rejected", which is
        a routing TARGET, never a member of spec.stages -- it must still get a
        visible card.
        """
        spec = sample_spec()
        doc = form_mockups_html(spec)
        off_slice = _card_slice(doc, "Closed - Rejected")
        assert "Rejection Reason" in off_slice
        assert "required-marker" in off_slice  # it is required=True in the fixture
        assert "kf-offspine" in off_slice

    def test_required_marker_present_only_on_required_fields(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        for f in spec.data_model.fields:
            row = _field_slice(doc, f.name)
            if f.required:
                assert "required-marker" in row, (
                    f"{f.name} is required but has no marker"
                )
            else:
                assert "required-marker" not in row, (
                    f"{f.name} is optional but has a marker"
                )

    def test_select_field_renders_its_real_options_from_the_backing_list(self):
        """
        Blocker 2 (round 1): a generic "-- select --" placeholder gives nothing to
        proof- read. The Select field "Equipment Type" (list_name="Equipment Type")
        must render its list's ACTUAL values as real <option> entries.
        """
        spec = sample_spec()
        doc = form_mockups_html(spec)
        lst = next(
            lst for lst in spec.master_data.lists if lst.name == "Equipment Type"
        )
        row = _field_slice(doc, "Equipment Type")
        for value in lst.values:
            assert f'<option value="{value}">{value}</option>' in row

    def test_table_grid_notes_row_cap_and_columns(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        capped_table = next(t for t in spec.data_model.tables if t.max_rows is not None)
        assert f"Max rows: {capped_table.max_rows}" in doc
        for col in capped_table.columns:
            assert col.name in doc

    def test_table_with_no_cap_says_no_cap_in_html(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert "Max rows: no cap" in doc
        assert "Max rows: None" not in doc

    def test_master_data_section_lists_every_list_and_every_value_verbatim(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert 'class="kf-master-data"' in doc
        for lst in spec.master_data.lists:
            list_slice_start = doc.index(f"<!-- list:{lst.name} -->")
            list_slice = doc[list_slice_start : list_slice_start + 2000]
            for value in lst.values:
                assert value in list_slice

    def test_process_summary_describes_decisions_and_loops(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert 'class="kf-process"' in doc
        rp = spec.routing.points[0]
        assert rp.at_stage in doc and rp.field_name in doc
        for option in rp.options:
            assert option in doc
        lp = spec.rework_loops.loops[0]
        assert lp.gate_field in doc and lp.from_stage in doc and lp.to_stage in doc

    def test_control_types_render_real_inputs(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        assert "<textarea" in doc  # Issue Description / Repair Notes
        assert "<select" in doc  # Equipment Type / Diagnosis Result
        assert 'type="checkbox"' in doc  # Rework Needed


class TestVisibilityAwareRendering:
    """
    Blocker 1: with none of this applied, a Hidden field rendered as a plain live
    input -- the customer proofread a form containing a field the built app hides.
    Round-1's own proof case (`VisibilityEntry(section='Triage', stage='Triage',
    permission=HIDDEN, field='Due Date')`) is exactly what sample_spec's "Due Date"
    field/entry mirrors.
    """

    def test_hidden_field_does_not_render_as_an_editable_control(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Due Date")
        assert "<input" not in row, "a Hidden field must not render as a live control"
        assert "hidden at this step" in row

    def test_readonly_field_renders_visibly_read_only(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Repair Notes")
        assert "disabled" in row
        assert "read-only" in row

    def test_ordinary_field_still_renders_a_live_editable_control(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(
            doc, "Customer Name"
        )  # covered only by a section-level Editable entry
        assert "<input" in row
        assert "disabled" not in row
        assert "hidden" not in row.lower()

    def test_field_with_no_visibility_entry_at_all_still_renders_editable(self):
        """
        No entry mentions "Closed - Rejected" at all -- must render as the platform
        default (an ordinary editable control), never as hidden.
        """
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Rejection Reason")
        assert "<textarea" in row
        assert "disabled" not in row

    def test_section_level_entry_governs_every_field_in_it(self):
        """
        "Section-level entries count too" -- Customer Name/Equipment Type are
        governed only by the SECTION-level Editable entry for "Customer Info" (no
        field-level entry names them), and both must render editable.
        """
        spec = sample_spec()
        doc = form_mockups_html(spec)
        for name in ("Customer Name", "Equipment Type"):
            row = _field_slice(doc, name)
            assert "disabled" not in row
            assert "hidden" not in row.lower()

    def test_table_level_hidden_entry_hides_the_whole_table(self):
        """
        Major 3's "banner+table pattern": a table name is ALSO a legal
        VisibilityEntry section -- hiding "Attachments Log" at its own stage must
        hide the whole grid.
        """
        base = sample_spec()
        hiding_entry = VisibilityEntry("Attachments Log", "Quality Check", "Hidden")
        spec = dataclasses.replace(
            base,
            visibility=VisibilityMatrix(
                entries=base.visibility.entries + (hiding_entry,)
            ),
        )
        doc = form_mockups_html(spec)
        table_slice = _marker_slice(
            doc,
            "<!-- table:Attachments Log -->",
            ("<!-- stage:", "<!-- table:"),
        )
        assert "hidden at this step" in table_slice
        assert "<table>" not in table_slice

    def test_table_without_a_hidden_entry_still_renders_its_grid(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        table_slice = _marker_slice(
            doc,
            "<!-- table:Parts Used -->",
            ("<!-- stage:", "<!-- table:"),
        )
        assert "<table>" in table_slice


class TestComputedFieldRendering:
    """
    Blocker 2: ComputedReq rendered nowhere, and its target rendered as a typed
    input, so the customer approved a form where a human types a value the app will
    auto-calculate.
    """

    def test_computed_target_is_marked_auto_calculated_not_a_live_input(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Estimated Cost")
        assert "<input" not in row
        assert "auto-calculated" in row

    def test_computed_target_shows_its_formula_intent(self):
        """
        formula_intent exists specifically to be read by a human -- it must actually
        render.
        """
        spec = sample_spec()
        doc = form_mockups_html(spec)
        computed = spec.data_model.computed[0]
        row = _field_slice(doc, "Estimated Cost")
        assert computed.formula_intent in row

    def test_computed_target_notes_its_source_fields(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        computed = spec.data_model.computed[0]
        row = _field_slice(doc, "Estimated Cost")
        for src in computed.source_fields:
            assert src in row


class TestSectionGrouping:
    """Major 3: SectionReq rendered nowhere -- a stage with two sections rendered as one
    undifferentiated card."""

    def test_two_sections_on_one_stage_render_as_two_distinct_named_blocks(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        intake_slice = _card_slice(doc, "Intake")
        for sec in spec.data_model.sections:
            if sec.stage != "Intake":
                continue
            assert sec.name in intake_slice
            assert sec.description in intake_slice

    def test_fields_appear_under_their_own_section_not_a_sibling_s(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        customer_info_start = doc.index("Customer Info")
        issue_details_start = doc.index("Issue Details")
        # "Customer Name"/"Equipment Type" belong to Customer Info, which renders before
        # Issue Details in field order -- assert their marker sits before the Issue
        # Details heading.
        assert doc.index("<!-- field:Customer Name -->") < issue_details_start
        assert doc.index("<!-- field:Issue Description -->") > customer_info_start


class TestColumnTypeConsistency:
    """Major 4: mockup._column_header_label used to show name+required only, while
    diagram._column_label already showed type -- the two must agree."""

    def test_mockup_and_diagram_show_the_same_column_type_text(self):
        spec = sample_spec()
        html_doc = form_mockups_html(spec)
        xml_doc = schema_diagram_xml(spec)
        table = spec.data_model.tables[0]
        for col in table.columns:
            expected = f"{col.name} : {col.type}"
            assert expected in html_doc, f"mockup missing {expected!r}"
            assert col.name in xml_doc and col.type in xml_doc


class TestFieldTypeStatedInWords:
    """
    Major 5: a field's type was never stated in words; an unmapped type (e.g. User)
    rendered pixel-identical to Text.
    """

    def test_known_type_is_stated_in_words(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        row = _field_slice(doc, "Customer Name")
        assert "(Text)" in row

    def test_unmapped_type_renders_differently_from_text_and_is_flagged(self):
        base = sample_spec()
        weird_field = Field(
            "Assigned Reviewer", "User", False, "Intake", section="Customer Info"
        )
        new_fields = base.data_model.fields + (weird_field,)
        spec = dataclasses.replace(
            base, data_model=dataclasses.replace(base.data_model, fields=new_fields)
        )
        doc = form_mockups_html(spec)
        text_row = _field_slice(doc, "Customer Name")
        weird_row = _field_slice(doc, "Assigned Reviewer")
        assert "(User)" in weird_row
        assert "no dedicated control" in weird_row
        assert "no dedicated control" not in text_row


class TestDeclaredVsDerivedTerminals:
    """
    Major 6: ProblemGoal.terminal_states/result_values rendered nowhere, and "Where
    the work ends" answered a DIFFERENT (derived-topology) question under that same
    heading.
    """

    def test_declared_terminal_states_and_result_values_render_labeled_as_declared(
        self,
    ):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        terminals_slice = doc[doc.index('class="kf-terminals"') :]
        assert "Declared by the business" in terminals_slice
        for state in spec.problem_goal.terminal_states:
            assert state in terminals_slice
        for result in spec.problem_goal.result_values:
            assert result in terminals_slice

    def test_derived_list_is_present_but_labeled_as_derived(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        terminals_slice = doc[doc.index('class="kf-terminals"') :]
        assert "derived from routing/loops" in terminals_slice

    def test_declared_and_derived_are_not_the_same_unlabeled_list(self):
        """
        A spec whose declared terminal_states DIFFER from the derived topology list
        must show BOTH, not silently prefer one -- proving the two are genuinely
        separate blocks, not one heading quietly answering only one of the two
        questions.
        """
        base = sample_spec()
        different_goal = dataclasses.replace(
            base.problem_goal,
            terminal_states=("Totally Custom End State",),
        )
        spec = dataclasses.replace(base, problem_goal=different_goal)
        doc = form_mockups_html(spec)
        terminals_slice = doc[doc.index('class="kf-terminals"') :]
        assert (
            "Totally Custom End State" in terminals_slice
        )  # declared, rendered even though
        # it names something the topology itself never computed
        assert (
            "Quality Check" in terminals_slice
        )  # still present in the DERIVED list below it


class TestSequenceRendering:
    """
    Major 7: SequenceReq prefix/padding rendered nowhere, yet it is the record id
    every user of the built app actually sees.
    """

    def test_sequence_format_is_rendered(self):
        spec = sample_spec()
        doc = form_mockups_html(spec)
        seq = spec.data_model.sequence
        assert seq is not None
        assert f"{seq.prefix}-{seq.padding}" in doc

    def test_prefix_already_carrying_a_dash_does_not_double_wire(self):
        """
        decision_01 item 2: a prefix may already end with the separator (e.g.
        `RPT-`); joining that with another dash double-wires it into `RPT--0001`. A
        trailing dash must not double.
        """
        assert _format_sequence("RPT-", "0001") == "RPT-0001"
        assert _format_sequence("RPR", "0001") == "RPR-0001"

    def test_no_sequence_means_no_note(self):
        base = sample_spec()
        spec = dataclasses.replace(
            base, data_model=dataclasses.replace(base.data_model, sequence=None)
        )
        doc = form_mockups_html(spec)
        # the CSS rule name itself is always present in the static <style> block
        # regardless of whether anything uses that class -- check for the actual
        # ELEMENT, not the class name.
        assert '<p class="kf-sequence-note">' not in doc


class TestPersonaPages:
    def test_well_formed_and_no_external_refs(self):
        doc = persona_pages_html(sample_spec())
        _assert_well_formed_html(doc)
        _assert_no_external_refs(doc)

    def test_kpis_and_actions_come_from_the_view_not_the_page(self):
        spec = sample_spec()
        doc = persona_pages_html(spec)
        for view in spec.personas.views:
            for kpi in view.kpis:
                assert kpi in doc
            for action in view.actions:
                assert action in doc
            for page in view.pages:
                assert page.name in doc

    def test_widget_renders_a_human_label_not_a_raw_repr(self):
        """
        Minor 14: app.application.intake.schema.WidgetIntent has no `.name` -- it
        must not fall through to a raw `WidgetIntent(slug=..., config=...,
        row_fields=...)` repr.
        """

        @dataclasses.dataclass(frozen=True)
        class WidgetIntent:
            slug: str
            config: tuple[tuple[str, str], ...] = ()
            row_fields: tuple[str, ...] = ()

        widget = WidgetIntent(
            slug="view/table", config=(("flow_type", "process"), ("view_id", "myitems"))
        )
        page = Page(name="My Queue", widgets=(widget,))
        view = PersonaView(role="Reviewer", pages=(page,), kpis=(), actions=())
        spec = dataclasses.replace(sample_spec(), personas=Personas(views=(view,)))
        doc = persona_pages_html(spec)
        assert "view/table" in doc
        assert "flow_type" in doc and "process" in doc
        assert "WidgetIntent(" not in doc
        assert "row_fields=" not in doc


class TestDesignBundle:
    def test_well_formed_and_no_external_refs(self):
        doc = design_bundle_html(sample_spec())
        _assert_well_formed_html(doc)
        _assert_no_external_refs(doc)

    def test_contains_both_diagrams_and_both_html_sections(self):
        spec = sample_spec()
        doc = design_bundle_html(spec)
        assert doc.count("&lt;mxGraphModel") == 2  # flow + schema, escaped inside <pre>
        assert 'class="kf-card' in doc  # form mockups section
        assert spec.personas.views[0].role in doc  # persona pages section
        assert 'class="kf-process"' in doc  # process summary
        assert 'class="kf-master-data"' in doc  # master data

    def test_raw_xml_inside_pre_reparses(self):
        spec = sample_spec()
        doc = design_bundle_html(spec)
        pres = re.findall(r"<pre>(.*?)</pre>", doc, flags=re.DOTALL)
        assert len(pres) == 2
        for raw in pres:
            xml_text = html.unescape(raw)
            ET.fromstring(xml_text)  # must be independently parseable once un-escaped
