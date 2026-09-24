"""Checklist test for the engine manual — what a fresh-context agent uses to
build ANY Kissflow app through this engine. The manual is CLAUDE.md (router +
always-loaded rules) plus one file per section under docs/engine/, because a
single 82KB CLAUDE.md reloads on every message. Verifies structure (mandatory
section headings), substance (marker phrases per section), size, and blindness
(no leaked identity from the app-specific source repo) across the whole corpus.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
DOC_PATH = ROOT / "CLAUDE.md"
SECTIONS_DIR = ROOT / "docs" / "engine"

# Exact heading strings, in the order the build proceeds. Order here is only
# documentation of intent — the slicing logic below tolerates any doc order.
HEADINGS = [
    "## THE RULE",
    "## Node-graph invariants",
    "## Workflow",
    "## Expressions",
    "## Gate polarity",
    "## Tables",
    "## Field events",
    "## Visibility",
    "## Members first",
    "## Write path",
    "## Item data plane",
    "## Pages",
    "## Build order",
]

# 2-4 distinctive lowercase substrings per section. Each must appear
# (case-insensitively) inside that section's own text block, not just
# anywhere in the doc — proves content lives under the right heading.
SECTION_MARKERS: dict[str, list[str]] = {
    "## THE RULE": ["prove nothing", "ui-built", "have not checked"],
    "## Node-graph invariants": [
        "6-unit",
        "createdat",
        "allowformatting",
        "capitalised",
    ],
    "## Workflow": ["strands in-flight", "gototask", "issuspended", "zero permissions"],
    "## Expressions": [
        "zero-arg function",
        "one of three",
        "case-sensitive",
        "six edits",
    ],
    "## Gate polarity": ["fail closed", "escapes the loop", "stays in the loop"],
    "## Tables": ["nested model", "maxrow", "cannot live inside a section"],
    "## Field events": ["async () =>", "kfsdk", "source field"],
    "## Visibility": [
        "section-level lever",
        "precedence between",
        "renders empty",
        "required is scoped",
    ],
    "## Members first": [
        "member/batch",
        "zero members",
        "approle",
        "err rather than ever reaching",
    ],
    "## Write path": [
        "_meta_version",
        "snapshot the draft",
        "archive before deleting",
        "tokens are not validated",
    ],
    "## Item data plane": ["read back", "aiid trap", "clears nothing"],
    "## Pages": ["raw hex", "viewing as", "only truth surface", "stepmetrics"],
    "## Build order": [
        "output-invariant audit",
        "403/500",
        "only 404 means wrong door",
        "dry-run",
    ],
}

HEADING_LINE = re.compile(r"^(## .+?)[ \t]*$", re.MULTILINE)


def _doc_text() -> str:
    """CLAUDE.md followed by every docs/engine/*.md, in filename order.

    Concatenating is safe for the checks below because section headings are
    unique across the corpus, so `_section_slice` still lands in exactly one
    file's text. A section may live in either place; what must not happen is
    its content disappearing.
    """
    assert DOC_PATH.exists(), (
        f"missing {DOC_PATH} — the engine manual must exist at worktree root"
    )
    assert SECTIONS_DIR.is_dir(), (
        f"missing {SECTIONS_DIR} — the split engine sections must exist"
    )
    parts = [DOC_PATH.read_text(encoding="utf-8")]
    section_files = sorted(SECTIONS_DIR.glob("*.md"))
    assert section_files, f"no section files in {SECTIONS_DIR}"
    parts.extend(p.read_text(encoding="utf-8") for p in section_files)
    return "\n\n".join(parts)


def _section_slice(doc: str, heading: str) -> str:
    """Text from `heading`'s line up to (not including) the next `## ` heading."""
    starts = [(m.start(), m.group(1)) for m in HEADING_LINE.finditer(doc)]
    idx = next((pos for pos, text in starts if text == heading), None)
    assert idx is not None, f"heading not found: {heading!r}"
    later = sorted(pos for pos, _ in starts if pos > idx)
    end = later[0] if later else len(doc)
    return doc[idx:end]


def test_doc_exists_and_min_length():
    text = _doc_text()
    assert len(text) > 8000, f"engine manual too short: {len(text)} chars (need > 8000)"


# CLAUDE.md reloads on every single message, so its size is a running cost, not
# a one-off. At 82KB it cost ~21k tokens per message. Detail belongs in
# docs/engine/, which is read on demand.
CLAUDE_MD_MAX_CHARS = 20_000


def test_claude_md_stays_a_router():
    size = len(DOC_PATH.read_text(encoding="utf-8"))
    assert size <= CLAUDE_MD_MAX_CHARS, (
        f"CLAUDE.md is {size} chars (max {CLAUDE_MD_MAX_CHARS}). It is reloaded on "
        "every message — move the new detail into docs/engine/ and link it from "
        "the section index."
    )


def test_all_section_headings_present():
    text = _doc_text()
    found = {m.group(1) for m in HEADING_LINE.finditer(text)}
    missing = [h for h in HEADINGS if h not in found]
    assert not missing, f"missing section headings: {missing}"


def _normalize(text: str) -> str:
    """Fold away cosmetic markdown noise a marker phrase must not be sensitive
    to: hard line-wraps splitting two words that read as one phrase, and
    backtick code-spans sitting between them. Never touch other punctuation
    (underscores are semantic here, e.g. the literal marker "_meta_version")."""
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text)


def test_section_marker_phrases():
    text = _doc_text()
    failures = []
    for heading in HEADINGS:
        section = _normalize(_section_slice(text, heading)).lower()
        for marker in SECTION_MARKERS[heading]:
            if marker not in section:
                failures.append(f"{heading!r} missing marker {marker!r}")
    assert not failures, "missing markers:\n" + "\n".join(failures)


def test_no_forbidden_tokens_in_doc():
    # Same split-string trick as tests/test_p0_scaffold.py: build the forbidden
    # tokens by concatenation so the literal substring never appears in THIS
    # file's own source (which is itself scanned by the repo-wide blindness test).
    forbidden = ["cli" + "nic", "ai" + "case", "cP" + "5", "คลิ" + "นิก"]
    text = _doc_text().lower()
    hits = [tok for tok in forbidden if tok.lower() in text]
    assert not hits, f"forbidden token(s) leaked into CLAUDE.md: {hits}"
