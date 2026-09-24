"""Contract tests for `scripts/arch_scan.py` (refactor spec, section 8, gate 3).

Three fixtures drive every test here, all module-scoped so the CLI runs exactly once per tree
per test session (spec's TDD test: "Run each CLI call once per module"):

  * `fixture_result` -- the CLI run against a copy of `tests/fixtures/arch_scan_bad/`, a small
    tree with exactly one violation of each scan next to one compliant case the scan must not
    report (`dict_draft_in_domain_api` holds three violations, one per rule path -- see
    `FIXTURE_EXPECTED`). The fixture's `.py` files are stored as `.py.txt` so ruff/ty/pytest
    never touch them directly; this test copies the tree into `tmp_path` and renames each one
    back to `.py` before running the CLI on the copy.
  * `forms_result` -- the CLI run against a copy of `tests/fixtures/arch_scan_forms/` (G0 review
    finding 4), a second tree that packs in every named form of the scans `arch_scan_bad` leaves
    untested: every accepted env-read shape, every FastMCP-runs-at-import-time shape, a
    port-method use scoped to `application/use_cases/`, and every tool-import shape.
  * `real_result` -- the CLI run against this repo's own `src/app` and `tests/unit`. Its counts
    are a ratchet (`CEILINGS`), not a pass/fail target: later goals lower them to zero one at a
    time as the refactor moves code, and this test only refuses a count that goes UP.

The CLI runs as a subprocess, never as an import: `scripts.arch_scan` cannot be resolved by `ty`
under the boilerplate clone's `root = ["./src"]` config (no "." root), so a direct import here
would fail that check once G1 copies it. A subprocess call has no such constraint.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_SRC = REPO_ROOT / "tests" / "fixtures" / "arch_scan_bad"
FORMS_FIXTURE_SRC = REPO_ROOT / "tests" / "fixtures" / "arch_scan_forms"

# The eight scan names, in spec section 8 order -- the same order the CLI's --json keys use.
SCAN_NAMES: tuple[str, ...] = (
    "env_reads_outside_settings",
    "module_level_fastmcp",
    "iserror_dicts",
    "adapter_methods_without_port",
    "port_methods_without_use_case",
    "tool_module_imports_own_family_only",
    "tests_mirror_src",
    "dict_draft_in_domain_api",
)

# The fixture's one violation per scan (spec: "Put exactly one violation of each scan in the
# fixture"). Exact match: the list must hold the violation(s) and must not hold the compliant
# case planted next to them.
#
# `dict_draft_in_domain_api` is the one deliberate exception (G0 review finding 2): a single
# function that triggers rule (a) and rule (b) at once lets a mutation that breaks only one rule
# hide behind the other rule still firing on that same function. Its fixture instead holds THREE
# functions, one per path -- rule (a) alone, rule (b) alone, and rule (a) through a quoted string
# annotation -- so each path's own mutation is caught on its own.
FIXTURE_EXPECTED: dict[str, list[str]] = {
    "env_reads_outside_settings": ["infrastructure/kissflow/leaky.py:11"],
    "module_level_fastmcp": ["infrastructure/mcp/server.py:8"],
    "iserror_dicts": ["infrastructure/kissflow/errors.py:9"],
    "adapter_methods_without_port": [
        "infrastructure/kissflow/widget.py:WidgetAdapter.fetch"
    ],
    "port_methods_without_use_case": [
        "application/interfaces/flow.py:FlowRepository.publish"
    ],
    "tool_module_imports_own_family_only": ["infrastructure/mcp/tools/flow.py:10:page"],
    "tests_mirror_src": ["infrastructure/kissflow/orphan.py"],
    "dict_draft_in_domain_api": [
        "domain/flow_draft.py:only_quoted_string_annotation",
        "domain/flow_draft.py:only_rule_a",
        "domain/flow_draft.py:only_rule_b",
    ],
}

# The `arch_scan_forms` tree's exact findings per scan (G0 review finding 4). Unlike
# `arch_scan_bad`'s one-violation-each design, this tree packs every named form into as few files
# as the scan's own scoping rules allow, so a single fixture proves each named form fires on its
# own line/qualname. A scan this tree adds no case for keeps its empty list -- e.g.
# `iserror_dicts`, `adapter_methods_without_port`, `tests_mirror_src` (every source file here has
# a mirror under this tree's own `tests/unit/`) and `dict_draft_in_domain_api` (this tree has no
# `domain/`), all already covered on `arch_scan_bad`.
FORMS_EXPECTED: dict[str, list[str]] = {
    "env_reads_outside_settings": [
        "infrastructure/kissflow/env_general_forms.py:18",
        "infrastructure/kissflow/env_general_forms.py:19",
        "infrastructure/kissflow/env_general_forms.py:20",
        "infrastructure/kissflow/env_general_forms.py:21",
        "infrastructure/kissflow/env_general_forms.py:22",
        "infrastructure/kissflow/env_general_forms.py:23",
        "infrastructure/kissflow/env_os_path.py:10",
    ],
    "module_level_fastmcp": [
        "infrastructure/mcp/fastmcp_forms.py:13",
        "infrastructure/mcp/fastmcp_forms.py:16",
        "infrastructure/mcp/fastmcp_forms.py:21",
        "infrastructure/mcp/fastmcp_forms.py:27",
    ],
    "iserror_dicts": [],
    "adapter_methods_without_port": [],
    "port_methods_without_use_case": [
        "application/interfaces/flow_port.py:FlowPort.publish"
    ],
    "tool_module_imports_own_family_only": [
        "infrastructure/mcp/tools/flow.py:14:page",
        "infrastructure/mcp/tools/flow.py:15:item",
        "infrastructure/mcp/tools/flow.py:16:widget",
        "infrastructure/mcp/tools/flow.py:17:gadget",
        "infrastructure/mcp/tools/flow.py:27:dataset",
    ],
    "tests_mirror_src": [],
    "dict_draft_in_domain_api": [],
}

# The real-tree ratchet. Every count below was checked with an independent method before being
# written here (see the writer's report): env_reads_outside_settings and tests_mirror_src against
# an independent grep/file-count that matches spec section 15's own G0 baseline numbers (23 lines
# in 5 files; 27, since tests/unit/ did not exist yet); the rest against a second, separately
# written script using a different technique (a plain grep for module-level classes' public defs,
# and a regex read of each signature's own text) that reproduced the same counts AND the same
# qualnames. Later goals lower each ceiling as the refactor moves the code these findings point
# at, down to 0 by the end -- re-measured after the G9 merge (G9a's value_objects/entities split
# plus G9b's FlowDraft/verify migration, both landed on top of P1/G6/G10): env_reads_outside_settings
# and dict_draft_in_domain_api are both 0 now (G9b's KF_PROCESS_TEMPLATE read left the domain
# entirely, resolved through Settings instead; G9a's nav.py/pages.py, the last dict-draft-typed
# public API, moved into entities/ with every function typed on FlowDraft/PageDraft/Navigation).
# tests_mirror_src is 16 (G9b deletes graph.py/expr.py/application/verify.py, each already
# missing a mirror at G0, and gives their two private successors -- entities/_flow_ops.py,
# entities/_flow_rules.py -- their own direct mirror tests; the Stage C shared-pieces commit
# then LOWERS it again, 17 -> 16: tests/unit/infrastructure/mcp/test_server.py, added for the
# new create_server(), incidentally gives infrastructure/mcp/server.py the mirror test it was
# missing at G0's own baseline).
# LOWERED by Stage D group 9 (meta, G13): tests/unit/infrastructure/test_playbook.py and
# test_capabilities.py give infrastructure/playbook.py and infrastructure/capabilities.py --
# both pre-dating this refactor, so both missing a mirror at G0 -- their own direct mirror
# tests. 16 -> 14. port_methods_without_use_case is also LOWERED by the same group: its two
# use cases (ForgePlaybook, ForgeCapabilities) give DocsReader.playbook and
# DocsReader.capabilities their first callers. 46 -> 44.
CEILINGS: dict[str, int] = {
    "env_reads_outside_settings": 0,
    "module_level_fastmcp": 0,
    # Stage E removes the last old success/error payload wrappers. Failures now
    # raise ApplicationError and the tool edge converts them to ToolError.
    "iserror_dicts": 0,
    "adapter_methods_without_port": 0,
    # RAISED by goal G7 (refactor spec's own exception, section 6 G7, reviewed 2026-09-22):
    # G7 adds the seven ports' 50 abstract methods (flow 18, app 13, page 6, dataset 4,
    # copilot 2, item 5, docs 2) before G11 (Stage D) adds their use cases, so every one of
    # them is, for now, a "port method without a use case" by construction. G11 lowers this
    # back to 0 as it adds each use case. No other ceiling in this table may go up.
    # LOWERED by Stage D: group 1 (flow fields) gave FlowRepository.get_draft, put_draft
    # and publish a caller; group 3 (flow workflow) added get_list_items. 50 -> 46. group 9
    # (meta) gave DocsReader.playbook and DocsReader.capabilities a caller. 46 -> 44.
    # group 5 (app roles and members) gave 6 more AppRepository methods a caller
    # (list_app_roles, get_app_role, put_app_role, get_assignee, create_app_role,
    # delete_app_role) and 4 more FlowRepository methods one (list_flows, get_members,
    # delete_member, post_member_batch). 44 -> 34, the real count
    # `python -m scripts.arch_scan --json` reports after the group 5 merge. group 6 (app
    # family apps) gave AppRepository.list_applications, create_application,
    # delete_application, get_app_draft, publish_app; FlowRepository.create_flow,
    # post_report_member_batch, get_flow_detail, list_lists; PageRepository.list_pages a
    # caller each (the other methods group 6's report listed already had a caller from
    # group 5). 34 -> 24, the real count `python -m scripts.arch_scan --json` reports
    # after the group 6 merge.
    # group 7 (page, dataset, item, copilot) gave PageRepository.create_page,
    # get_page_draft, put_page_draft, AppRepository.put_app_draft, DatasetRepository's four
    # methods, ItemService's five methods and CopilotService's two methods a caller.
    # 24 -> 8, the real count `python -m scripts.arch_scan --json` reports after the
    # group 7 merge. group 4 (flow lifecycle) gave the remaining FlowRepository,
    # AppRepository and PageRepository methods its nine use cases call a caller.
    # Stage E removes the two archive helpers that only delete methods called
    # internally. The adapters keep the archive request inline in delete.
    "port_methods_without_use_case": 0,
    "tool_module_imports_own_family_only": 0,
    # LOWERED by Stage D group 9 (meta): infrastructure/playbook.py and
    # infrastructure/capabilities.py each got their own direct mirror test. 16 -> 14.
    # Verified unchanged by the group 8 merge (design and intake): every new module it
    # adds under use_cases/design/, use_cases/intake/, models/requests/design/,
    # models/requests/intake/, models/responses/design/ and models/responses/intake/
    # has its own mirror test. Real count after the group 8 merge: still 14.
    "tests_mirror_src": 0,
    "dict_draft_in_domain_api": 0,
}


def _run_cli(root: Path, tests_unit: Path) -> dict[str, Any]:
    """Run `python -m scripts.arch_scan --json` as a subprocess and parse its output.

    Args:
        root: The `--root` argument: the package directory to scan.
        tests_unit: The `--tests-unit` argument: the unit-test tree to check mirrors against.

    Returns:
        The parsed JSON object: scan name -> `{"count": int, "findings": [str, ...]}`.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.arch_scan",
            "--json",
            "--root",
            str(root),
            "--tests-unit",
            str(tests_unit),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"scan CLI exited {proc.returncode}\nstderr:\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


def _materialize(src: Path, dest_parent: Path) -> Path:
    """Copy a `.py.txt` fixture tree into `dest_parent` and rename every file back to `.py`, so
    ruff/ty/pytest ignore the originals but the CLI sees real source files.

    Args:
        src: The fixture tree to copy, such as `tests/fixtures/arch_scan_bad`.
        dest_parent: The temporary directory to copy the fixture tree into.

    Returns:
        The path to the copied fixture directory (`dest_parent / src.name`).
    """
    dest = dest_parent / src.name
    shutil.copytree(src, dest)
    for txt_file in dest.rglob("*.py.txt"):
        txt_file.rename(txt_file.with_suffix(""))
    return dest


def _materialize_fixture(dest_parent: Path) -> Path:
    """Copy `tests/fixtures/arch_scan_bad/` into `dest_parent` and rename every `.py.txt` file
    to `.py` (see `_materialize`).

    Args:
        dest_parent: The temporary directory to copy the fixture tree into.

    Returns:
        The path to the copied `arch_scan_bad` directory.
    """
    return _materialize(FIXTURE_SRC, dest_parent)


@pytest.fixture(scope="module")
def fixture_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The CLI's `--json` output against the materialized `arch_scan_bad` fixture tree."""
    dest = _materialize_fixture(tmp_path_factory.mktemp("arch_scan_bad"))
    return _run_cli(dest / "src" / "app", dest / "tests" / "unit")


@pytest.fixture(scope="module")
def forms_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The CLI's `--json` output against the materialized `arch_scan_forms` fixture tree (G0
    review finding 4): broader per-scan form coverage than `arch_scan_bad`'s one-violation-each
    tree, added because most scan rules had no test at all beyond their fixture's single case."""
    dest = _materialize(FORMS_FIXTURE_SRC, tmp_path_factory.mktemp("arch_scan_forms"))
    return _run_cli(dest / "src" / "app", dest / "tests" / "unit")


@pytest.fixture(scope="module")
def real_result() -> dict[str, Any]:
    """The CLI's `--json` output against this repo's own `src/app` and `tests/unit`."""
    return _run_cli(REPO_ROOT / "src" / "app", REPO_ROOT / "tests" / "unit")


# =================================================================================================
# CLI contract
# =================================================================================================


def test_json_output_has_the_eight_scans_in_section_8_order(
    fixture_result: dict[str, Any],
) -> None:
    """The --json keys are exactly the eight scan names, in spec section 8's order."""
    assert list(fixture_result.keys()) == list(SCAN_NAMES)


def test_json_shape_is_count_and_findings(fixture_result: dict[str, Any]) -> None:
    """Each scan's value is `{"count": N, "findings": [...]}` with count == len(findings)."""
    for name in SCAN_NAMES:
        entry = fixture_result[name]
        assert set(entry) == {"count", "findings"}
        assert entry["count"] == len(entry["findings"])


def test_plain_text_output_is_one_line_per_scan(tmp_path: Path) -> None:
    """Without --json, the CLI prints `<scan_name>: <count>`, one line per scan, exit code 0."""
    dest = _materialize_fixture(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.arch_scan",
            "--root",
            str(dest / "src" / "app"),
            "--tests-unit",
            str(dest / "tests" / "unit"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == len(SCAN_NAMES)
    for name, line in zip(SCAN_NAMES, lines, strict=True):
        assert line == f"{name}: {len(FIXTURE_EXPECTED[name])}"


# =================================================================================================
# Fixture tree: exact findings per scan
# =================================================================================================


@pytest.mark.parametrize("scan_name", SCAN_NAMES)
def test_fixture_scan_reports_exactly_its_one_violation(
    fixture_result: dict[str, Any], scan_name: str
) -> None:
    """Each scan's findings on the fixture tree equal exactly its planted violation(s) -- never
    empty (the scan must fire), and never one entry more than `FIXTURE_EXPECTED` (the compliant
    case next to them must not be reported)."""
    assert fixture_result[scan_name]["findings"] == FIXTURE_EXPECTED[scan_name]


# =================================================================================================
# Forms tree: broader per-rule form coverage (G0 review finding 4)
# =================================================================================================


@pytest.mark.parametrize("scan_name", SCAN_NAMES)
def test_forms_scan_reports_exactly_its_expected_findings(
    forms_result: dict[str, Any], scan_name: str
) -> None:
    """Each scan's findings on the `arch_scan_forms` tree equal exactly `FORMS_EXPECTED` -- every
    named form in the G0 brief (env-read and FastMCP shapes, port-method use scoped to
    `application/use_cases/`, and every tool-import shape) fires, and nothing else does."""
    assert forms_result[scan_name]["findings"] == FORMS_EXPECTED[scan_name]


# =================================================================================================
# Real tree: the ratchet
# =================================================================================================


@pytest.mark.parametrize("scan_name", SCAN_NAMES)
def test_real_tree_count_matches_its_ceiling(
    real_result: dict[str, Any], scan_name: str
) -> None:
    """The real `src/app` count for each scan equals its recorded ceiling (spec section 15's NULL
    baseline). A scan is reported, never targeted (section 8): this is a ratchet against
    regression, not a pass/fail gate on the count itself -- later goals lower each ceiling to 0
    as they move the code a finding points at."""
    actual = real_result[scan_name]["count"]
    ceiling = CEILINGS[scan_name]
    if actual > ceiling:
        message = (
            f"{scan_name}: regression -- count went from {ceiling} to {actual}. "
            f"New findings: {sorted(set(real_result[scan_name]['findings']))}"
        )
    elif actual < ceiling:
        message = f"{scan_name}: lower CEILINGS[{scan_name!r}] to {actual}"
    else:
        message = ""
    assert actual == ceiling, message
