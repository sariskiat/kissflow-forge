"""Contract test over the copilot query bank (map #42, ticket #44)."""

from __future__ import annotations

import json

import pytest

from app.application.querybank import (
    ANSWER,
    GRAPH_DIFF,
    MODULES,
    SWEEPS,
    build_bank,
    main,
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


def test_main_default(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main([])
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    assert len(lines) == len(BANK)
    first = json.loads(lines[0])
    assert "id" in first
    assert "prompt" in first


def test_main_sweep_filter(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["--sweep", "pages"])
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    expected_count = len([q for q in BANK if q.sweep == "pages"])
    assert len(lines) == expected_count
    for line in lines:
        data = json.loads(line)
        assert data["sweep"] == "pages"


def test_main_observable_filter(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["--observable", ANSWER])
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    expected_count = len([q for q in BANK if q.observable == ANSWER])
    assert len(lines) == expected_count
    for line in lines:
        data = json.loads(line)
        assert data["observable"] == ANSWER


def test_main_combined_filter(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["--sweep", "roles", "--observable", GRAPH_DIFF])
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    expected_count = len([q for q in BANK if q.sweep == "roles" and q.observable == GRAPH_DIFF])
    assert len(lines) == expected_count
    for line in lines:
        data = json.loads(line)
        assert data["sweep"] == "roles"
        assert data["observable"] == GRAPH_DIFF


def test_main_count(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["--count"])
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    assert lines[-1] == f"total\t{len(BANK)}"

    counts: dict[str, int] = {}
    for line in lines[:-1]:
        sweep, count_str = line.split("\t")
        counts[sweep] = int(count_str)

    assert sum(counts.values()) == len(BANK)
    assert set(counts.keys()) == set(SWEEPS)


def test_main_count_with_filter(capsys: pytest.CaptureFixture[str]) -> None:
    ret = main(["--count", "--sweep", "pages", "--observable", ANSWER])
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    expected_count = len([q for q in BANK if q.sweep == "pages" and q.observable == ANSWER])
    assert lines == [f"pages\t{expected_count}", f"total\t{expected_count}"]


def test_main_implicit_argv(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["querybank", "--count", "--sweep", "boards"])
    ret = main()
    assert ret == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.strip().split("\n") if line]
    expected_count = len([q for q in BANK if q.sweep == "boards"])
    assert lines == [f"boards\t{expected_count}", f"total\t{expected_count}"]
