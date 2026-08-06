"""Unit tests for the live-write client. NO network: transport is stubbed."""
from __future__ import annotations

import pytest

from kfforge.client import ApplyReport, Err, KfClient, KfConfig, apply_fields
from kfforge.types import FieldSpec, FieldType

DEV = KfConfig(key_id="k", key_secret="s", account="Acc", domain="dev-x.example.com", app_id="App")


def _bare_form_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
    }


class FakeClient(KfClient):
    """KfClient with the HTTP verb intercepted — exercises the real read-verify-write logic."""

    def __init__(self, draft: dict) -> None:
        super().__init__(DEV)
        self.draft = draft
        self.published = False
        self.puts = 0

    def get_draft(self, kind, flow_id):  # type: ignore[override]
        return self.draft

    def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
        live = self.draft.get("_meta_version")
        if expect_version is not None and live != expect_version:
            return Err("conflict", f"expected {expect_version!r}, live {live!r}")
        self.puts += 1
        new["_meta_version"] = "v2"
        self.draft = new
        return new

    def publish(self, kind, flow_id):  # type: ignore[override]
        self.published = True


def test_prod_domain_is_refused() -> None:
    """The dev-guard is the whole safety story — a non-dev domain must never build a config."""
    got = KfConfig(key_id="k", key_secret="s", account="A", domain="kissflow.com", app_id="App")
    assert "dev-" not in got.domain  # sanity: the fixture really is a prod-shaped domain
    with pytest.MonkeyPatch.context() as mp:
        for k, v in {"KF_DEV_ACCESS_KEY_ID": "k", "KF_DEV_ACCESS_KEY_SECRET": "s",
                     "KF_DEV_ACCOUNT_ID": "A", "KF_DEV_DOMAIN": "acme.kissflow.com"}.items():
            mp.setenv(k, v)
        err = KfConfig.from_env()
    assert isinstance(err, Err) and err.kind == "config"


def test_missing_env_returns_err_not_keyerror() -> None:
    with pytest.MonkeyPatch.context() as mp:
        for k in ("KF_DEV_ACCESS_KEY_ID", "KF_DEV_ACCESS_KEY_SECRET",
                  "KF_DEV_ACCOUNT_ID", "KF_DEV_DOMAIN"):
            mp.delenv(k, raising=False)
        got = KfConfig.from_env()
    assert isinstance(got, Err) and got.kind == "config"


def test_apply_fields_adds_and_verifies() -> None:
    c = FakeClient(_bare_form_draft())
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXTAREA)])
    assert isinstance(rep, ApplyReport)
    assert rep.added == ("alpha",) and rep.verified == ("alpha",)
    assert rep.missing == () and rep.skipped == ()
    assert rep.as_tool_result()["isError"] is False


def test_apply_fields_is_idempotent_and_writes_nothing_second_time() -> None:
    c = FakeClient(_bare_form_draft())
    spec = [FieldSpec(name="alpha", type=FieldType.TEXT)]
    apply_fields(c, "form", "F1", spec)
    rep = apply_fields(c, "form", "F1", spec)
    assert isinstance(rep, ApplyReport)
    assert rep.added == () and rep.skipped == ("alpha",) and rep.verified == ("alpha",)
    assert c.puts == 1, "re-applying an existing field must not issue a second PUT"


def test_conflict_when_draft_moved_under_us() -> None:
    c = FakeClient(_bare_form_draft())
    got = c.put_draft("form", "F1", _bare_form_draft(), expect_version="stale")
    assert isinstance(got, Err) and got.kind == "conflict"


def test_bad_field_type_is_rejected_before_any_write() -> None:
    c = FakeClient(_bare_form_draft())
    got = apply_fields(c, "form", "F1",
                       [FieldSpec(name="x", type="Formula")])  # type: ignore[arg-type]
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0, "an invalid change set must never reach the network"


def test_publish_is_skipped_when_a_field_is_missing_on_read_back() -> None:
    """Output-invariant audit: never publish a draft that failed verification."""
    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            return new  # accepted, but self.draft is NOT updated -> read-back lacks the field

    c = Dropping(_bare_form_draft())
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="ghost", type=FieldType.TEXT)], publish=True)
    assert isinstance(rep, ApplyReport)
    assert rep.missing == ("ghost",) and rep.published is False
    assert rep.as_tool_result()["isError"] is True
    assert c.published is False
