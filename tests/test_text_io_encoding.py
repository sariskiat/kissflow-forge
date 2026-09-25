"""Every text read or write in `src/app` must name its encoding.

Colleagues run the server on Windows, where Python 3.13 reads a file with no
`encoding=` as cp1252, not UTF-8. The served skills, capability docs and shapes
are UTF-8: read as cp1252, three of them raised `UnicodeDecodeError` (the
builder playbook among them) and the rest came back garbled. No Windows CI
exists, so this scan is the guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC: Path = Path(__file__).resolve().parent.parent / "src" / "app"
TEXT_METHODS = {"read_text", "write_text", "open"}


def _mode(call: ast.Call) -> str:
    """The literal mode of an `open(...)` call, or "" when it is not a literal."""
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    args = call.args[1:] if isinstance(call.func, ast.Name) else call.args
    if args and isinstance(args[0], ast.Constant):
        return str(args[0].value)
    return ""


def _unencoded_calls(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_text_call = (
            isinstance(func, ast.Attribute) and func.attr in TEXT_METHODS
        ) or (isinstance(func, ast.Name) and func.id == "open")
        if not is_text_call or "b" in _mode(node):
            continue
        if not any(kw.arg == "encoding" for kw in node.keywords):
            lines.append(node.lineno)
    return lines


def test_every_text_read_and_write_in_src_names_its_encoding() -> None:
    missing = [
        f"{path.relative_to(SRC.parent).as_posix()}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        for line in _unencoded_calls(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not missing, f"add encoding='utf-8' at: {missing}"
