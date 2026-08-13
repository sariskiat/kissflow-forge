"""P0 acceptance: blindness, severed umbilical, explicit app, server boots."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", ".ruff_cache", "node_modules"}
TEXT_EXT = {".py", ".json", ".md", ".robot", ".toml", ".txt", ".yml", ".yaml", ".cfg"}
# Case-insensitive "cli"+"nic" and "ai"+"case" subsume the old underscore/concatenated
# tokens AND close the dash/space/possessive + app-abbreviation gaps the case-sensitive
# ones missed -- a green scan now really means blind. Tokens built by concatenation so
# this file's own source stays grep-clean.
FORBIDDEN = re.compile("|".join(["cli" + "nic", "ai" + "case", "cP" + "5", "คลิ" + "นิก"]), re.IGNORECASE)


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
    """App is no longer required at config load — it can be chosen per call (app_id) or at
    runtime (forge_use_app). But an app IS still required to actually build: the guard moved to
    the _client() chokepoint, which fails loud (require_app=True) when no app is resolvable."""
    import kfforge.server as srv
    from kfforge.client import Err, KfConfig
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "s")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "a")
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-example.test")
    monkeypatch.delenv("KF_APP", raising=False)

    # config load now succeeds with an empty app_id (no boot-time lock)
    cfg = KfConfig.from_env()
    assert isinstance(cfg, KfConfig) and cfg.app_id == ""
    # a per-call override flows through
    overridden = KfConfig.from_env(app_id_override="App_X")
    assert isinstance(overridden, KfConfig) and overridden.app_id == "App_X"
    # but building a client for a build tool still refuses without a resolved app
    guarded = srv._client()
    assert isinstance(guarded, Err) and "app" in guarded.message.lower()
    # the discovery path (list/use app) is allowed with no app selected
    assert not isinstance(srv._client(require_app=False), Err)
    # and a per-call app_id satisfies the guard
    assert not isinstance(srv._client("App_X"), Err)


def test_server_exposes_original_8_tools():
    import kfforge.server as srv
    expected = {"kf_list_field_types", "kf_plan_field_change", "kf_get_flow_schema",
                "kf_apply_field_change", "kf_create_process", "kf_plan_step_visibility",
                "kf_set_step_visibility", "kf_publish"}
    found = {name for name in dir(srv) if name.startswith("kf_")}
    missing = expected - found
    assert not missing, f"tools missing from server module: {missing}"
