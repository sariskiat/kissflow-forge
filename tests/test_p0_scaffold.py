"""P0 acceptance: blindness, severed umbilical, explicit app, server boots."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", ".ruff_cache", "node_modules"}
TEXT_EXT = {".py", ".json", ".md", ".robot", ".toml", ".txt", ".yml", ".yaml", ".cfg"}
FORBIDDEN = re.compile("|".join(["AI_" + "Clinic", "ai" + "clinic", "cP" + "5", "คลิ" + "นิก"]))


def _repo_text_files():
    for p in ROOT.rglob("*"):
        if any(part in SKIP_DIRS or part.startswith(".env") for part in p.parts):
            continue
        if p.is_file() and p.suffix in TEXT_EXT and p.name != "test_p0_scaffold.py":
            yield p


def test_blindness_no_real_app_tokens():
    hits = [str(p) for p in _repo_text_files() if FORBIDDEN.search(p.read_text(errors="ignore"))]
    assert hits == [], f"real-app knowledge leaked into: {hits}"


def test_no_kfmcp_references():
    hits = [str(p) for p in _repo_text_files()
            if p.suffix == ".py" and ("kf" + "mcp") in p.read_text(errors="ignore")]
    assert hits == [], f"umbilical to old repo not severed: {hits}"


def test_client_requires_explicit_app(monkeypatch):
    from kfforge.client import Err, KfConfig
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "s")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "a")
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-example.test")
    monkeypatch.delenv("KF_APP", raising=False)
    cfg = KfConfig.from_env()
    assert isinstance(cfg, Err) and "KF_APP" in cfg.message


def test_server_exposes_original_8_tools():
    import kfforge.server as srv
    expected = {"kf_list_field_types", "kf_plan_field_change", "kf_get_flow_schema",
                "kf_apply_field_change", "kf_create_process", "kf_plan_step_visibility",
                "kf_set_step_visibility", "kf_publish"}
    found = {name for name in dir(srv) if name.startswith("kf_")}
    missing = expected - found
    assert not missing, f"tools missing from server module: {missing}"
