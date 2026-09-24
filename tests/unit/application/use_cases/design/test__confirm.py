"""Spec for app.application.use_cases.design._confirm: the approval protocol
(confirmation package, digest, explicit approval, revisions).

Ported verbatim from `tests/test_design.py` (its confirm.py section), Stage D
group 8. Every assertion is unchanged; only the import path moved.
"""

from __future__ import annotations

import dataclasses
import re
import xml.etree.ElementTree as ET

import pytest
from tests.fakes.design_stubs import (
    ReworkLoops,
    VisibilityEntry,
    VisibilityMatrix,
    _assert_well_formed_html,
    sample_spec,
    spec_with_forward_loop,
    spec_with_two_routing_points_same_stage,
)

from app.application.use_cases.design._confirm import (
    ConfirmationRequest,
    apply_revisions,
    is_approved,
    request_confirmation,
)

# --------------------------------------------------------------------------------------
# confirm.py
# --------------------------------------------------------------------------------------


class TestRequestConfirmation:
    def test_artifacts_present_and_parseable(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        assert isinstance(req, ConfirmationRequest)
        assert set(req.artifacts) == {
            "flow_diagram.drawio",
            "schema_diagram.drawio",
            "design.html",
        }
        ET.fromstring(req.artifacts["flow_diagram.drawio"])
        ET.fromstring(req.artifacts["schema_diagram.drawio"])
        _assert_well_formed_html(req.artifacts["design.html"])

    def test_digest_is_a_sha256_hex_string(self):
        req = request_confirmation(sample_spec())
        assert re.fullmatch(r"[0-9a-f]{64}", req.spec_digest)

    def test_questions_cover_every_routing_literal(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        for rp in spec.routing.points:
            for option in rp.options:
                assert any(option in q and rp.at_stage in q for q in req.questions), (
                    f"no question covers routing literal {option!r} at {rp.at_stage!r}"
                )

    def test_questions_cover_every_loop_gate(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        for lp in spec.rework_loops.loops:
            assert any(lp.gate_field in q and lp.from_stage in q for q in req.questions)

    def test_forward_loop_question_does_not_claim_it_loops_back(self):
        spec = spec_with_forward_loop()
        req = request_confirmation(spec)
        lp = spec.rework_loops.loops[0]
        matching = [q for q in req.questions if lp.gate_field in q]
        assert matching
        assert not any(
            "วนกลับไปที่" in q for q in matching
        )  # never the backward-loop phrasing
        assert any(
            "ไปข้างหน้า" in q for q in matching
        )  # flags it as going forward instead

    def test_questions_cover_every_terminal_state(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        assert any("Quality Check" in q for q in req.questions)
        assert any("Closed - Rejected" in q for q in req.questions)

    def test_questions_cover_every_required_field(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        for f in spec.data_model.fields:
            if f.required:
                assert any(f.name in q for q in req.questions)

    def test_questions_cover_every_master_data_list_byte_exact(self):
        """
        Note "Equipment Type" is both a FIELD name (required-field question) and a
        LIST name (master-data question) in the fixture on purpose -- a naive "first
        question whose text contains the list name" pick would land on the wrong
        one, so this checks that AT LEAST ONE matching question carries every value,
        not just the first match.
        """
        spec = sample_spec()
        req = request_confirmation(spec)
        for lst in spec.master_data.lists:
            matching = [q for q in req.questions if lst.name in q]
            assert matching, f"no question covers list {lst.name!r}"
            assert any(all(v in q for v in lst.values) for q in matching), (
                f"no question for list {lst.name!r} carries every value byte-exact"
            )

    def test_questions_are_thai_confirm_revise_prompts(self):
        req = request_confirmation(sample_spec())
        assert req.questions
        for q in req.questions:
            assert any("฀" <= ch <= "๿" for ch in q), f"not Thai: {q!r}"


class TestDigestChangesWithSpec:
    def test_same_content_same_digest(self):
        d1 = request_confirmation(sample_spec()).spec_digest
        d2 = request_confirmation(sample_spec()).spec_digest
        assert d1 == d2

    def test_changed_spec_changes_digest(self):
        spec1 = sample_spec()
        spec2 = dataclasses.replace(spec1, app_name="Different Name")
        d1 = request_confirmation(spec1).spec_digest
        d2 = request_confirmation(spec2).spec_digest
        assert d1 != d2

    def test_deep_mutation_inside_a_wrapper_also_changes_digest(self):
        spec1 = sample_spec()
        new_loops = ReworkLoops(
            loops=(
                dataclasses.replace(
                    spec1.rework_loops.loops[0], gate_field="Different Gate"
                ),
            )
        )
        spec2 = dataclasses.replace(spec1, rework_loops=new_loops)
        d1 = request_confirmation(spec1).spec_digest
        d2 = request_confirmation(spec2).spec_digest
        assert d1 != d2

    def test_visibility_mutation_changes_digest(self):
        """
        The digest must see through the visibility matrix too, not just the
        dimensions round 1 already covered.
        """
        spec1 = sample_spec()
        new_entries = spec1.visibility.entries + (
            VisibilityEntry(
                "Quality Check", "Quality Check", "ReadOnly", field="Rework Needed"
            ),
        )
        spec2 = dataclasses.replace(
            spec1, visibility=VisibilityMatrix(entries=new_entries)
        )
        d1 = request_confirmation(spec1).spec_digest
        d2 = request_confirmation(spec2).spec_digest
        assert d1 != d2

    def test_approval_on_old_digest_does_not_carry_to_a_revised_spec(self):
        spec1 = sample_spec()
        req1 = request_confirmation(spec1)
        decision = "approve"
        assert is_approved(spec1, decision) is True
        approved_digest = req1.spec_digest

        spec2 = apply_revisions(spec1, {"app_name": "Equipment Repair Intake (v2)"})
        req2 = request_confirmation(spec2)

        assert req2.spec_digest != approved_digest, (
            "a revised spec must never silently inherit an earlier approval's digest"
        )


class TestIsApproved:
    @pytest.mark.parametrize(
        "decision,expected",
        [
            ("approve", True),
            ("Approve", False),
            ("approved", False),
            ("reject", False),
            ("revise", False),
            ("", False),
        ],
    )
    def test_only_explicit_approve_is_true(self, decision, expected):
        assert is_approved(sample_spec(), decision) is expected


class TestApplyRevisions:
    def test_unknown_key_raises_naming_valid_keys(self):
        spec = sample_spec()
        with pytest.raises(ValueError) as exc_info:
            apply_revisions(spec, {"not_a_real_key": "x"})
        message = str(exc_info.value)
        assert "app_name" in message  # at least one real valid key is named

    def test_app_name_revision_applies_and_is_pure(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"app_name": "Renamed Intake"})
        assert revised.app_name == "Renamed Intake"
        assert spec.app_name == "Equipment Repair Intake"  # original untouched

    def test_stage_attribute_revision_applies_to_only_that_stage(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"stage:Intake:owner_role": "Reception"})
        by_name = {s.name: s for s in revised.stages.stages}
        assert by_name["Intake"].owner_role == "Reception"
        assert by_name["Diagnosis"].owner_role == "Technician"  # untouched
        assert spec.stages.stages[0].owner_role == "Front Desk"  # original untouched

    # ---- M9: a sibling decision point at the shared stage must never cause a false
    # raise ----

    def test_routing_target_revision_at_a_shared_stage_touches_only_the_matching_point(
        self,
    ):
        """
        m10 (round 2, REQUIRED regression guard for M9):
        spec_with_two_routing_points_same_ stage() existed in round 1 but was never
        fed to apply_revisions -- that hole is exactly what let M9 through (the
        option-existence raise fired on the FIRST routing point at a shared stage
        regardless of which one actually had the option).
        """
        spec = spec_with_two_routing_points_same_stage()
        revised = apply_revisions(spec, {"routing-target:Middle:A": "Start"})
        by_field = {rp.field_name: rp for rp in revised.routing.points}
        assert dict(by_field["First Choice"].route_per_option)["A"] == ("Start",)
        # the SIBLING decision point (whose options are C/D, not A/B) must be untouched
        assert dict(by_field["Second Choice"].route_per_option) == {
            "C": ("End",),
            "D": ("Start",),
        }

    def test_routing_option_revision_at_a_shared_stage_touches_only_the_matching_point(
        self,
    ):
        spec = spec_with_two_routing_points_same_stage()
        revised = apply_revisions(spec, {"routing-option:Middle:C": "C-renamed"})
        by_field = {rp.field_name: rp for rp in revised.routing.points}
        assert "C-renamed" in by_field["Second Choice"].options
        assert by_field["First Choice"].options == ("A", "B")  # sibling untouched

    def test_routing_target_revision_raises_only_when_no_point_at_the_stage_has_the_option(  # noqa: E501
        self,
    ):
        spec = spec_with_two_routing_points_same_stage()
        with pytest.raises(ValueError, match="no option"):
            apply_revisions(
                spec, {"routing-target:Middle:Z": "Start"}
            )  # "Z" is nobody's option

    def test_routing_target_revision_changes_where_an_option_routes(self):
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"routing-target:Diagnosis:Beyond Repair": "Closed - Escalated"}
        )
        rp = revised.routing.points[0]
        mapping = dict(rp.route_per_option)
        assert mapping["Beyond Repair"] == ("Closed - Escalated",)
        assert mapping["Repairable"] == ("Repair",)  # untouched
        assert dict(spec.routing.points[0].route_per_option)["Beyond Repair"] == (
            "Closed - Rejected",
        )

    def test_routing_option_revision_fixes_a_miscased_literal_preserving_its_target(
        self,
    ):
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"routing-option:Diagnosis:Needs Parts": "Needs parts"}
        )
        rp = revised.routing.points[0]
        assert "Needs parts" in rp.options
        assert "Needs Parts" not in rp.options
        assert dict(rp.route_per_option)["Needs parts"] == (
            "Repair",
        )  # target preserved

    # ---- M10: stage rename must cascade into visibility/sections/test-cases too ----

    def test_stage_rename_cascades_into_visibility_and_section_and_test_cases(self):
        """
        M10: proven necessary against a real AppSpec (cross-tree verification
        script) -- a bare rename that skipped visibility.stage, SectionReq.stage,
        CaseWalk.expected_path, and StepFill.stage returned a spec
        app.application.intake.compile.compile_spec() rejected.
        """
        spec = sample_spec()
        revised = apply_revisions(spec, {"stage:Repair:rename": "Fix"})

        assert {s.name for s in revised.stages.stages} == {
            "Intake",
            "Diagnosis",
            "Fix",
            "Quality Check",
        }

        rp = revised.routing.points[0]
        mapping = dict(rp.route_per_option)
        assert mapping["Repairable"] == ("Fix",)
        assert mapping["Needs Parts"] == ("Fix",)

        lp = revised.rework_loops.loops[0]
        assert lp.to_stage == "Fix"

        # SectionReq.stage
        repair_work = next(
            sec for sec in revised.data_model.sections if sec.name == "Repair Work"
        )
        assert repair_work.stage == "Fix"
        # VisibilityEntry.stage (both the section-level and field-level Repair-stage
        # entries)
        repair_entries = [
            e for e in revised.visibility.entries if e.section == "Repair Work"
        ]
        assert repair_entries
        assert all(e.stage == "Fix" for e in repair_entries)
        # VisibilityEntry.section is an EXPLICIT name ("Repair Work"), unrelated to the
        # stage's own name ("Repair") -- must NOT be touched by the rename.
        assert all(e.section == "Repair Work" for e in repair_entries)

        # test case: expected_path and the matching StepFill.stage
        case = revised.test_cases.cases[0]
        assert "Fix" in case.expected_path
        assert "Repair" not in case.expected_path
        fill_stages = {f.stage for f in case.fills}
        assert "Fix" in fill_stages
        assert "Repair" not in fill_stages

        # original spec is untouched (pure)
        assert spec.stages.stages[2].name == "Repair"
        assert spec.test_cases.cases[0].expected_path == (
            "Intake",
            "Diagnosis",
            "Repair",
            "Quality Check",
        )

    def test_stage_rename_cascades_visibility_section_when_it_is_the_implicit_default(
        self,
    ):
        """
        The OTHER visibility-section shape: "Quality Check" stage's own entry uses
        the IMPLICIT default section (section name == stage name, no SectionReq
        object) -- renaming the stage must rename BOTH `.stage` and `.section` on
        that one entry. A DIFFERENT entry naming an unrelated EXPLICIT section that
        merely happens to share the old stage's `.stage` (the table-visibility
        entry, section="Attachments Log") must have its `.stage` renamed but its
        `.section` left alone -- these are two different entries, checked
        separately.
        """
        spec = sample_spec()
        original = next(
            e
            for e in spec.visibility.entries
            if e.stage == "Quality Check" and e.section == "Quality Check"
        )
        revised = apply_revisions(spec, {"stage:Quality Check:rename": "QA"})

        implicit_matches = [
            e
            for e in revised.visibility.entries
            if e.permission == original.permission
            and e.field == original.field
            and e.stage == "QA"
            and e.section == "QA"
        ]
        assert implicit_matches, (
            "the implicit-default-section entry must have BOTH stage and "
            "section renamed"
        )
        assert not any(
            e.stage == "Quality Check" or e.section == "Quality Check"
            for e in revised.visibility.entries
        )

    def test_stage_rename_unknown_name_raises(self):
        spec = sample_spec()
        with pytest.raises(ValueError):
            apply_revisions(spec, {"stage:Nonexistent Stage:rename": "X"})

    # ---- M11: list-value rename must cascade into routing and test cases ----

    def test_list_value_revision_cascades_into_routing_and_test_case(self):
        """
        M11: proven necessary against a real AppSpec -- renaming a list value in
        isolation left a routing option and a test-case fill referencing the OLD
        literal, which compile_spec()'s _check_routing_literals/_check_test_cases
        both rejected.
        """
        spec = sample_spec()
        revised = apply_revisions(
            spec,
            {
                "list:Diagnosis Result Options:value:Repairable": (
                    "Repairable (confirmed)"
                )
            },
        )
        lst = next(
            lst
            for lst in revised.master_data.lists
            if lst.name == "Diagnosis Result Options"
        )
        assert "Repairable (confirmed)" in lst.values
        assert "Repairable" not in lst.values

        rp = revised.routing.points[0]
        assert "Repairable (confirmed)" in rp.options
        assert "Repairable" not in rp.options
        assert dict(rp.route_per_option)["Repairable (confirmed)"] == ("Repair",)

        case = revised.test_cases.cases[0]
        diagnosis_fill = next(f for f in case.fills if f.stage == "Diagnosis")
        assert (
            dict(diagnosis_fill.values)["Diagnosis Result"] == "Repairable (confirmed)"
        )

        # original untouched (pure)
        assert "Repairable" in spec.master_data.lists[1].values
        original_diagnosis_fill = next(
            f for f in spec.test_cases.cases[0].fills if f.stage == "Diagnosis"
        )
        assert dict(original_diagnosis_fill.values)["Diagnosis Result"] == "Repairable"

    def test_list_value_revision_with_no_backing_field_still_applies(self):
        """
        A list value that backs no field at all (or none that drives routing/appears
        in a test case) should still rename cleanly -- no cascade needed, no error
        either.
        """
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"list:Equipment Type:value:Router": "Wireless Router"}
        )
        lst = next(
            lst for lst in revised.master_data.lists if lst.name == "Equipment Type"
        )
        assert "Wireless Router" in lst.values
        assert "Router" not in lst.values
        assert len(lst.values) == 4  # replaced in place, not appended

    def test_list_value_unknown_value_raises(self):
        spec = sample_spec()
        with pytest.raises(ValueError):
            apply_revisions(spec, {"list:Equipment Type:value:Nonexistent": "X"})

    # ---- remaining widened-vocabulary keys (round 1, re-verified against the new
    # fixture) ----

    def test_loop_gate_field_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"loop:Quality Check:Repair:gate_field": "Needs Rework"}
        )
        assert revised.rework_loops.loops[0].gate_field == "Needs Rework"
        assert spec.rework_loops.loops[0].gate_field == "Rework Needed"

    def test_loop_direction_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"loop:Quality Check:Repair:to_stage": "Diagnosis"}
        )
        assert revised.rework_loops.loops[0].to_stage == "Diagnosis"
        assert revised.rework_loops.loops[0].from_stage == "Quality Check"

    def test_field_required_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"field:Repair:Repair Notes:required": "true"})
        f = next(f for f in revised.data_model.fields if f.name == "Repair Notes")
        assert f.required is True
        original = next(f for f in spec.data_model.fields if f.name == "Repair Notes")
        assert original.required is False

    def test_field_rename_revision_applies(self):
        spec = sample_spec()
        revised = apply_revisions(
            spec, {"field:Repair:Repair Notes:rename": "Technician Notes"}
        )
        names = {f.name for f in revised.data_model.fields if f.stage == "Repair"}
        assert "Technician Notes" in names
        assert "Repair Notes" not in names

    def test_table_max_rows_revision_applies_including_no_cap(self):
        spec = sample_spec()
        revised = apply_revisions(spec, {"table:Parts Used:max_rows": "25"})
        t = next(t for t in revised.data_model.tables if t.name == "Parts Used")
        assert t.max_rows == 25

        revised_none = apply_revisions(spec, {"table:Parts Used:max_rows": "none"})
        t2 = next(t for t in revised_none.data_model.tables if t.name == "Parts Used")
        assert t2.max_rows is None

    def test_multiple_revisions_in_one_call(self):
        spec = sample_spec()
        revised = apply_revisions(
            spec,
            {
                "app_name": "Renamed",
                "stage:Intake:owner_role": "Reception",
            },
        )
        assert revised.app_name == "Renamed"
        assert revised.stages.stages[0].owner_role == "Reception"

    def test_every_question_category_has_a_matching_revision_key(self):
        spec = sample_spec()
        req = request_confirmation(spec)
        rp = spec.routing.points[0]
        apply_revisions(
            spec, {f"routing-option:{rp.at_stage}:{rp.options[0]}": "Renamed Option"}
        )
        apply_revisions(
            spec, {f"routing-target:{rp.at_stage}:{rp.options[0]}": "Somewhere Else"}
        )
        lp = spec.rework_loops.loops[0]
        apply_revisions(
            spec, {f"loop:{lp.from_stage}:{lp.to_stage}:gate_field": "New Gate"}
        )
        rf = next(f for f in spec.data_model.fields if f.required)
        apply_revisions(spec, {f"field:{rf.stage}:{rf.name}:required": "false"})
        lst = spec.master_data.lists[0]
        apply_revisions(
            spec, {f"list:{lst.name}:value:{lst.values[0]}": "Renamed Value"}
        )
        assert req.questions  # sanity: there really were questions to answer
