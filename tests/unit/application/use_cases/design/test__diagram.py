"""Spec for app.application.use_cases.design._diagram: the draw.io flow and
schema diagrams.

Ported verbatim from `tests/test_design.py` (its diagram.py section), Stage D
group 8. Every assertion is unchanged; only the import path moved.
"""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET

import pytest
from tests.fakes.design_stubs import (
    AppSpec,
    DataModel,
    Loop,
    MasterData,
    Personas,
    ReworkLoops,
    Routing,
    Stage,
    Stages,
    TestCases,
    VisibilityMatrix,
    _assert_valid_mxgraph,
    _attr,
    _child,
    _empty_problem_goal,
    bare_shape_spec,
    sample_spec,
    spec_with_branch_local_loop,
    spec_with_forward_loop,
    spec_with_multistage_branches,
    spec_with_orphan_stage,
    spec_with_sequential_splits,
    spec_with_tiered_branches,
    spec_with_tricky_text,
    spec_with_two_routing_points_same_stage,
)

from app.application.use_cases.design._diagram import (
    _loop_direction,
    _stage_index,
    flow_diagram_xml,
    schema_diagram_xml,
    verify_flow_diagram_branches,
)

# --------------------------------------------------------------------------------------
# diagram.py
# --------------------------------------------------------------------------------------


class TestFlowDiagram:
    def test_parses_as_valid_mxgraph_and_every_edge_resolves(self):
        spec = sample_spec()
        _assert_valid_mxgraph(flow_diagram_xml(spec))

    def test_bare_sequence_shape_also_works(self):
        _assert_valid_mxgraph(flow_diagram_xml(bare_shape_spec()))

    def test_one_decision_node_per_routing_point(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        diamonds = [
            c
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1" and "rhombus" in (c.get("style") or "")
        ]
        assert len(diamonds) == len(spec.routing.points)

    def test_one_dashed_back_edge_per_genuine_backward_loop(self):
        spec = (
            sample_spec()
        )  # its one loop (Quality Check -> Repair) IS a genuine backward loop
        root = ET.fromstring(flow_diagram_xml(spec))
        dashed_edges = [
            c
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and "dashed=1" in (c.get("style") or "")
        ]
        assert len(dashed_edges) == len(spec.rework_loops.loops)

    def test_branch_local_loop_renders_a_dashed_edge_between_its_branch_stages(self):
        """
        S3 (#34) AC4: a loop whose BOTH endpoints are stages of one multi-stage
        branch (Verify -> Fix) renders one dashed backward edge, and it resolves to
        those branch stages' own vertices -- the diagram draws the branch-local
        loop, not just spine loops.
        """
        spec = spec_with_branch_local_loop()
        doc = flow_diagram_xml(spec)
        _assert_valid_mxgraph(
            doc
        )  # every edge (incl. this loop) resolves to a real vertex
        root = ET.fromstring(doc)
        cells = {c.get("id"): c for c in root.findall(".//mxCell")}
        dashed = [
            c
            for c in cells.values()
            if c.get("edge") == "1" and "dashed=1" in (c.get("style") or "")
        ]
        assert len(dashed) == 1
        edge = dashed[0]
        endpoints = {
            cells[edge.get("source")].get("value"),
            cells[edge.get("target")].get("value"),
        }
        assert endpoints == {"Verify", "Fix"}
        assert "Fix Approved" in (edge.get("value") or "")

    def test_loop_edge_labeled_with_gate_field(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        dashed_values = [
            c.get("value")
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and "dashed=1" in (c.get("style") or "")
        ]
        assert any(
            spec.rework_loops.loops[0].gate_field in (v or "") for v in dashed_values
        )

    def test_stage_box_second_line_is_owner_role(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        values = [
            c.get("value") or ""
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1"
        ]
        stage = spec.stages.stages[0]
        assert any(
            stage.name in v and stage.owner_role in v and "<br>" in v for v in values
        )

    def test_empty_spec_still_produces_valid_xml(self):
        empty = AppSpec(
            app_name="Empty",
            problem_goal=_empty_problem_goal(),
            stages=Stages(stages=()),
            routing=Routing(points=()),
            rework_loops=ReworkLoops(loops=()),
            data_model=DataModel(fields=(), tables=()),
            master_data=MasterData(lists=()),
            visibility=VisibilityMatrix(entries=()),
            personas=Personas(views=()),
            test_cases=TestCases(cases=()),
        )
        _assert_valid_mxgraph(flow_diagram_xml(empty))

    def test_business_text_with_special_chars_and_thai_survives_two_decodes(self):
        """
        Minor 11: every style here sets html=1, so a value is HTML-rendered, not
        shown as plain text. After the ONE decode ElementTree performs, a raw
        '<'/'>' from the business name must NOT appear (that would mean it can be
        reinterpreted as a tag once mxGraph's HTML-mode renderer sees it) -- but
        after a SECOND decode (html.unescape, simulating what that renderer itself
        performs before painting the text), the original business text must be fully
        recovered.
        """
        spec = spec_with_tricky_text()
        xml_str = flow_diagram_xml(spec)
        root = _assert_valid_mxgraph(xml_str)
        joined_once = "\n".join(c.get("value") or "" for c in root.findall(".//mxCell"))
        assert (
            "<Urgent>" not in joined_once
        )  # would mean it survived as a raw, re-interpretable tag
        joined_twice = html.unescape(joined_once)
        assert spec.stages.stages[0].name in joined_twice
        assert spec.stages.stages[0].owner_role in joined_twice

    def test_two_routing_points_on_same_stage_do_not_overlap(self):
        spec = spec_with_two_routing_points_same_stage()
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        diamonds = [
            c
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1" and "rhombus" in (c.get("style") or "")
        ]
        assert len(diamonds) == 2
        coords = {
            (
                float(_attr(_child(c, "mxGeometry"), "x")),
                float(_attr(_child(c, "mxGeometry"), "y")),
            )
            for c in diamonds
        }
        assert len(coords) == 2, (
            "two routing points at the same stage rendered at identical coordinates"
        )

    def test_next_stage_box_does_not_overlap_the_decision_diamond(self):
        """
        Minor 8: the diamond(s) below a routing stage must not overlap the NEXT
        stage's box.
        """
        spec = (
            spec_with_two_routing_points_same_stage()
        )  # worst case: 2 stacked diamonds at "Middle"
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        diamonds = [
            c for c in root.findall(".//mxCell") if "rhombus" in (c.get("style") or "")
        ]
        assert len(diamonds) == 2
        diamond_bottoms = [
            float(_attr(_child(c, "mxGeometry"), "y"))
            + float(_attr(_child(c, "mxGeometry"), "height"))
            for c in diamonds
        ]
        end_stage = next(
            c
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1" and (c.get("value") or "").startswith("End<br>")
        )
        end_y = float(_attr(_child(end_stage, "mxGeometry"), "y"))
        assert max(diamond_bottoms) <= end_y, (
            "decision diamond overlaps the next stage box"
        )

    def test_orphan_stage_is_flagged_not_fabricated_an_edge(self):
        spec = spec_with_orphan_stage()
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        flagged = [
            c
            for c in root.findall(".//mxCell")
            if "unreachable" in (c.get("value") or "").lower()
        ]
        assert len(flagged) == 1, "exactly stage B should be flagged unreachable"
        b_cell = flagged[0]
        assert (b_cell.get("value") or "").startswith("B "), (
            "the flagged node should really be stage B"
        )
        b_id = b_cell.get("id")
        incoming = [
            c
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and c.get("target") == b_id
        ]
        assert not incoming, "orphan stage must not have a fabricated incoming edge"

    def test_reachable_stage_is_not_flagged(self):
        spec = spec_with_orphan_stage()
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        c_cell = next(
            c
            for c in root.findall(".//mxCell")
            if (c.get("value") or "").startswith("C<br>")
        )
        assert "unreachable" not in (c_cell.get("value") or "").lower()

    def test_forward_loop_is_not_drawn_dashed_and_is_not_mislabeled(self):
        spec = spec_with_forward_loop()
        idx = _stage_index(spec)
        assert _loop_direction(idx, spec.rework_loops.loops[0]) == "forward"
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        loop_edges = [
            c
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and "Weird Gate" in (c.get("value") or "")
        ]
        assert loop_edges
        assert "dashed=1" not in (loop_edges[0].get("style") or "")
        assert "forward" in (loop_edges[0].get("value") or "").lower()

    def test_fallback_nodes_for_unresolved_names_do_not_stack(self):
        """
        Minor 9: multiple unresolved names must not all land on the identical
        coordinate.
        """
        stages = Stages(stages=(Stage("Only", "Role", "..."),))
        rework_loops = ReworkLoops(
            loops=(
                Loop(from_stage="Ghost A", to_stage="Ghost B", gate_field="G1"),
                Loop(from_stage="Ghost C", to_stage="Ghost D", gate_field="G2"),
            )
        )
        spec = AppSpec(
            app_name="Fallback Test",
            problem_goal=_empty_problem_goal(),
            stages=stages,
            routing=Routing(points=()),
            rework_loops=rework_loops,
            data_model=DataModel(fields=(), tables=()),
            master_data=MasterData(lists=()),
            visibility=VisibilityMatrix(entries=()),
            personas=Personas(views=()),
            test_cases=TestCases(cases=()),
        )
        root = _assert_valid_mxgraph(flow_diagram_xml(spec))
        ghost_coords = set()
        for name in ("Ghost A", "Ghost B", "Ghost C", "Ghost D"):
            cell = next(
                c for c in root.findall(".//mxCell") if (c.get("value") or "") == name
            )
            geo = _child(cell, "mxGeometry")
            ghost_coords.add((geo.get("x"), geo.get("y")))
        assert len(ghost_coords) == 4, f"fallback nodes stacked: {ghost_coords}"


class TestBranchRenderPreCheck:
    """
    #4: the machine pre-check that the rendered diagram's branch structure matches
    the spec's routing, so a regression in the render can never put a lying
    confirmation diagram in front of an approver. `flow_diagram_xml` runs it on
    every render; these tests also feed the verifier deliberately-tampered XML
    directly and confirm it raises.
    """

    @staticmethod
    def _cell_id(root: ET.Element, name: str) -> str:
        # A box's label is either the bare name (a fallback minted by resolve()) or
        # name<br>role -- match the first line, same rule the verifier itself uses.
        return next(
            _attr(c, "id")
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1"
            and (c.get("value") or "").split("<br>", 1)[0] == name
        )

    def test_faithful_render_passes(self):
        spec = sample_spec()
        verify_flow_diagram_branches(spec, flow_diagram_xml(spec))  # must not raise

    def test_removing_a_fork_option_edge_raises(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        parent = _child(root, ".//root")
        dia_id = next(
            c.get("id")
            for c in root.findall(".//mxCell")
            if "rhombus" in (c.get("style") or "")
        )
        victim = next(
            c
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1"
            and c.get("source") == dia_id
            and (c.get("value") or "") == "Repairable"
        )
        parent.remove(victim)
        with pytest.raises(ValueError, match="Repairable"):
            verify_flow_diagram_branches(spec, ET.tostring(root, encoding="unicode"))

    def test_removing_the_diamond_raises(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        parent = _child(root, ".//root")
        dia = next(
            c for c in root.findall(".//mxCell") if "rhombus" in (c.get("style") or "")
        )
        dia_id = dia.get("id")
        parent.remove(dia)
        for c in list(root.findall(".//mxCell")):
            if c.get("edge") == "1" and dia_id in (c.get("source"), c.get("target")):
                parent.remove(c)
        with pytest.raises(ValueError, match="Diagnosis Result"):
            verify_flow_diagram_branches(spec, ET.tostring(root, encoding="unicode"))

    def test_sequential_spine_edge_through_a_split_raises(self):
        """
        The exact lie this ticket exists for: a plain spine edge drawn out of a fork
        stem, as if the branches were sequential steps.
        """
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        parent = _child(root, ".//root")
        stem_id = self._cell_id(root, "Diagnosis")
        repair_id = self._cell_id(root, "Repair")
        fake = ET.SubElement(
            parent,
            "mxCell",
            {
                "id": "tamper1",
                "value": "",
                "style": "edgeStyle=orthogonalEdgeStyle;html=1;",
                "edge": "1",
                "parent": "1",
                "source": stem_id,
                "target": repair_id,
            },
        )
        ET.SubElement(fake, "mxGeometry", {"relative": "1", "as": "geometry"})
        with pytest.raises(ValueError, match="[Ss]equential"):
            verify_flow_diagram_branches(spec, ET.tostring(root, encoding="unicode"))

    def test_option_edge_to_the_wrong_branch_entry_raises(self):
        spec = sample_spec()
        root = ET.fromstring(flow_diagram_xml(spec))
        victim = next(
            c
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and (c.get("value") or "") == "Beyond Repair"
        )
        victim.set(
            "target", self._cell_id(root, "Repair")
        )  # should go to Closed - Rejected
        with pytest.raises(ValueError, match="Beyond Repair"):
            verify_flow_diagram_branches(spec, ET.tostring(root, encoding="unicode"))

    def test_render_itself_runs_the_pre_check(self, monkeypatch):
        """
        flow_diagram_xml must call the verifier on its own output -- the gate lives
        in the render path, not only as an opt-in helper.
        """
        import app.application.use_cases.design._diagram as diagram_mod

        called: list[str] = []
        real = diagram_mod.verify_flow_diagram_branches
        monkeypatch.setattr(
            diagram_mod,
            "verify_flow_diagram_branches",
            lambda spec, xml: called.append("yes") or real(spec, xml),
        )
        flow_diagram_xml(sample_spec())
        assert called == ["yes"]


class TestFlowDiagramBranchMerge:
    """
    Round-1 defect (major, decision_01 item 1): three service tiers must each reach
    the shared merge directly -- NOT by spilling forward through a sibling branch.
    The merge's in-degree must equal the number of branches, and no cross-branch
    spine edge may appear.
    """

    @staticmethod
    def _first_line(value: str) -> str:
        # after ElementTree decodes the XML, an html=1 two-line label is
        # "Name<br>Role"; split on the DECODED tag (the raw file keeps &lt;br&gt;, the
        # parsed tree has <br>).
        return value.split("<br>", 1)[0].strip()

    def _vertex_id(self, root, name: str) -> str:
        for c in root.findall(".//mxCell"):
            if (
                c.get("vertex") == "1"
                and self._first_line(c.get("value") or "") == name
            ):
                return c.get("id")
        raise AssertionError(f"no vertex named {name!r}")

    def _incoming(self, root, target_id: str) -> set[str]:
        return {
            c.get("source")
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and c.get("target") == target_id
        }

    def _edge_pairs(self, root) -> set[tuple[str, str]]:
        return {
            (c.get("source"), c.get("target"))
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1"
        }

    def _vertex_labels(self, root) -> dict[str, str]:
        # vertex id -> its first line ("Self Service" out of "Self Service<br>Analyst")
        return {
            c.get("id"): self._first_line(c.get("value") or "")
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1"
        }

    def test_merge_in_degree_equals_branch_count(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_tiered_branches()))
        summary = self._vertex_id(root, "Summary")
        labels = self._vertex_labels(root)
        sources = {
            labels[_attr(c, "source")]
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1" and c.get("target") == summary and c.get("source")
        }
        # every branch's terminal feeds the merge: Self Service, Light Confirm, Full
        # Confirm
        assert sources == {"Self Service", "Light Confirm", "Full Confirm"}, sources

    def test_no_cross_branch_spine_edge(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_tiered_branches()))
        pairs = self._edge_pairs(root)
        assert (
            self._vertex_id(root, "Self Service"),
            self._vertex_id(root, "Light Work"),
        ) not in pairs, "self tier must not spill into the light tier"
        assert (
            self._vertex_id(root, "Light Confirm"),
            self._vertex_id(root, "Full Tier"),
        ) not in pairs, "light tier must not spill into the full tier"

    def test_each_branch_tail_feeds_the_merge_as_an_edge(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_tiered_branches()))
        pairs = self._edge_pairs(root)
        summary = self._vertex_id(root, "Summary")
        assert (self._vertex_id(root, "Self Service"), summary) in pairs
        assert (self._vertex_id(root, "Light Confirm"), summary) in pairs
        assert (self._vertex_id(root, "Full Confirm"), summary) in pairs


class TestFlowDiagramMultiStageBranchSequences:
    """
    S1 (#32): a route sequence of >=2 stages must draw its own interior stages
    truthfully -- s0 -> s1 -> ... -> sk explicit intra-branch edges, sk (the LAST
    stage) -> merge, and no interior stage may spill into a sibling branch's stages.
    The fork edges themselves (diamond -> each branch's first stage) were already
    correct before this fix; only the forward edges INSIDE a multi-stage branch were
    wrong.
    """

    @staticmethod
    def _first_line(value: str) -> str:
        return value.split("<br>", 1)[0].strip()

    def _vertex_id(self, root, name: str) -> str:
        for c in root.findall(".//mxCell"):
            if (
                c.get("vertex") == "1"
                and self._first_line(c.get("value") or "") == name
            ):
                return c.get("id")
        raise AssertionError(f"no vertex named {name!r}")

    def _edge_pairs(self, root) -> set[tuple[str, str]]:
        return {
            (c.get("source"), c.get("target"))
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1"
        }

    def test_intra_branch_edge_follows_the_sequence_order(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        pairs = self._edge_pairs(root)
        a1, a2 = self._vertex_id(root, "A1"), self._vertex_id(root, "A2")
        assert (a1, a2) in pairs, (
            "A1 -> A2 must be drawn explicitly for a multi-stage sequence"
        )

    def test_branch_terminal_is_the_last_sequence_stage_not_the_entry(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        pairs = self._edge_pairs(root)
        a2, wrap = self._vertex_id(root, "A2"), self._vertex_id(root, "Wrap")
        assert (a2, wrap) in pairs, (
            "A2 (the branch's LAST stage) must be the one that jumps to the merge"
        )

    def test_entry_stage_does_not_skip_ahead_to_the_merge(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        pairs = self._edge_pairs(root)
        a1, wrap = self._vertex_id(root, "A1"), self._vertex_id(root, "Wrap")
        assert (a1, wrap) not in pairs, (
            "A1 is not the branch terminal -- it must not jump to the merge"
        )

    def test_interior_branch_stage_does_not_spill_into_the_sibling_branch(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        pairs = self._edge_pairs(root)
        a2, b1 = self._vertex_id(root, "A2"), self._vertex_id(root, "B1")
        assert (a2, b1) not in pairs, (
            "A2 must not spill forward into sibling branch B's stage B1"
        )

    def test_single_stage_branch_still_reaches_the_merge_directly(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        pairs = self._edge_pairs(root)
        b1, wrap = self._vertex_id(root, "B1"), self._vertex_id(root, "Wrap")
        assert (b1, wrap) in pairs

    def test_fork_edges_land_on_each_branchs_first_stage(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        spec = spec_with_multistage_branches()
        diamond = next(
            c
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1" and "rhombus" in (c.get("style") or "")
        )
        a1, b1 = self._vertex_id(root, "A1"), self._vertex_id(root, "B1")
        # the fork edge from the diamond carries the option label ("A"/"B")
        fork_edges = {
            (c.get("source"), c.get("target"), c.get("value") or "")
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1"
        }
        assert (diamond.get("id"), a1, "A") in fork_edges
        assert (diamond.get("id"), b1, "B") in fork_edges
        assert spec.routing.points[0].options == (
            "A",
            "B",
        )  # sanity: fixture matches assumption

    def test_a2_is_not_flagged_unreachable(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_multistage_branches()))
        a2 = next(
            c
            for c in root.findall(".//mxCell")
            if c.get("vertex") == "1" and self._first_line(c.get("value") or "") == "A2"
        )
        assert "unreachable" not in (a2.get("value") or "").lower()


class TestFlowDiagramSequentialSplits:
    """
    S2 (#33): a branch terminal must rejoin at ITS OWN split's merge, never spill
    across a LATER, sequentially-following split. Same edge-extraction style as
    TestFlowDiagramMultiStageBranchSequences (S1) -- reuses the identical helpers.
    """

    @staticmethod
    def _first_line(value: str) -> str:
        return value.split("<br>", 1)[0].strip()

    def _vertex_id(self, root, name: str) -> str:
        for c in root.findall(".//mxCell"):
            if (
                c.get("vertex") == "1"
                and self._first_line(c.get("value") or "") == name
            ):
                return c.get("id")
        raise AssertionError(f"no vertex named {name!r}")

    def _edge_pairs(self, root) -> set[tuple[str, str]]:
        return {
            (c.get("source"), c.get("target"))
            for c in root.findall(".//mxCell")
            if c.get("edge") == "1"
        }

    def test_split_a_terminal_rejoins_at_its_own_merge_stemb(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_sequential_splits()))
        pairs = self._edge_pairs(root)
        a2, stem_b = self._vertex_id(root, "A2"), self._vertex_id(root, "StemB")
        assert (a2, stem_b) in pairs, (
            "split A's branch terminal (A2) must rejoin at StemB"
        )

    def test_split_a_terminal_does_not_spill_across_split_b(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_sequential_splits()))
        pairs = self._edge_pairs(root)
        a2, b1 = self._vertex_id(root, "A2"), self._vertex_id(root, "B1")
        a2, end = self._vertex_id(root, "A2"), self._vertex_id(root, "End")
        assert (a2, b1) not in pairs, (
            "split A's terminal must not spill into split B's own branch"
        )
        assert (a2, end) not in pairs, (
            "split A's terminal must not jump straight to split B's merge, "
            "skipping split B's diamond"
        )

    def test_split_b_terminal_rejoins_at_the_final_stage(self):
        root = _assert_valid_mxgraph(flow_diagram_xml(spec_with_sequential_splits()))
        pairs = self._edge_pairs(root)
        b1, end = self._vertex_id(root, "B1"), self._vertex_id(root, "End")
        assert (b1, end) in pairs, "split B's branch terminal (B1) must rejoin at End"


class TestSchemaDiagram:
    def test_parses_as_valid_mxgraph(self):
        spec = sample_spec()
        _assert_valid_mxgraph(schema_diagram_xml(spec))

    def test_field_rows_show_name_type_and_required_marker(self):
        spec = sample_spec()
        root = ET.fromstring(schema_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell")]
        required_field = next(f for f in spec.data_model.fields if f.required)
        optional_field = next(f for f in spec.data_model.fields if not f.required)
        assert any(
            required_field.name in v and required_field.type in v and "*" in v
            for v in values
        )
        assert any(
            optional_field.name in v
            and optional_field.type in v
            and v.strip()
            and "*" not in v
            for v in values
        )

    def test_table_box_shows_columns_and_max_rows(self):
        spec = sample_spec()
        root = ET.fromstring(schema_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell")]
        table = spec.data_model.tables[0]
        for col in table.columns:
            assert any(col.name in v and col.type in v for v in values)
        assert any(str(table.max_rows) in v for v in values)

    def test_table_with_no_max_rows_says_no_cap(self):
        spec = sample_spec()
        no_cap_table = next(t for t in spec.data_model.tables if t.max_rows is None)
        root = ET.fromstring(schema_diagram_xml(spec))
        values = [c.get("value") or "" for c in root.findall(".//mxCell")]
        assert any("no cap" in v.lower() for v in values)
        assert not any("max rows: none" in v.lower() for v in values)
        assert no_cap_table.name  # sanity: the fixture really has one

    def test_list_rendered_as_note_box(self):
        spec = sample_spec()
        root = ET.fromstring(schema_diagram_xml(spec))
        lst = spec.master_data.lists[0]
        note_cells = [
            c
            for c in root.findall(".//mxCell")
            if "shape=note" in (c.get("style") or "")
        ]
        assert any(lst.name in (c.get("value") or "") for c in note_cells)

    def test_business_text_with_special_chars_and_thai_survives_two_decodes(self):
        spec = spec_with_tricky_text()
        root = _assert_valid_mxgraph(schema_diagram_xml(spec))
        joined_twice = html.unescape(
            "\n".join(c.get("value") or "" for c in root.findall(".//mxCell"))
        )
        assert spec.stages.stages[0].name in joined_twice
