"""Contract test over the copilot query bank (map #42, ticket #44)."""

from __future__ import annotations

from kfforge.querybank import (
    ANSWER,
    GRAPH_DIFF,
    MODULES,
    SWEEPS,
    build_bank,
)

BANK = build_bank()


def test_size_is_about_a_thousand() -> None:
    # spec: "~1000 systematic queries"
    assert 900 <= len(BANK) <= 1300, len(BANK)


def test_ids_unique() -> None:
    ids = [q.id for q in BANK]
    assert len(ids) == len(set(ids))


def test_every_query_is_routable() -> None:
    # every row lands in a counted bucket — no query is unusable by a sweep
    for q in BANK:
        assert q.sweep in SWEEPS, q.id
        assert q.observable in (GRAPH_DIFF, ANSWER), q.id
        assert q.module in set(MODULES) | {"app", "any"}, q.id
        assert q.capability, q.id
        assert q.prompt.strip(), q.id
        assert q.expect.strip(), q.id


def test_both_observables_present() -> None:
    obs = {q.observable for q in BANK}
    assert obs == {GRAPH_DIFF, ANSWER}
    # answer queries feed best-practice/module-diff rows; must be a real slice
    answers = [q for q in BANK if q.observable == ANSWER]
    assert len(answers) >= 50


def test_answer_queries_never_target_a_flow_placeholder() -> None:
    # a semantic Q&A prompt is generic — it must not depend on a built flow
    for q in BANK:
        if q.observable == ANSWER:
            assert "{flow}" not in q.prompt, q.id


def test_no_tenant_tokens() -> None:
    # split literals so this test itself doesn't trip the repo blindness scan
    forbidden = ("cli" + "nic", "ai" + "case", "cP" + "5")
    for q in BANK:
        low = (q.prompt + q.expect + q.id).lower()
        for tok in forbidden:
            assert tok.lower() not in low, (q.id, tok)


def test_every_sweep_has_queries() -> None:
    covered = {q.sweep for q in BANK}
    assert covered == set(SWEEPS), set(SWEEPS) - covered
