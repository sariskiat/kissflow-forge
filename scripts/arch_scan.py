"""Static architecture scans for the boilerplate-alignment refactor.

Each public scan function below is one row of the refactor spec
(``docs/specs/refactor-to-mcp-boilerplate.md``, section 8, gate 3). A scan reads source with
:mod:`ast` and never imports the code it scans -- the scanned tree may be mid-refactor,
half-broken, or a throwaway fixture, and importing it would require it to actually run.

Run as a script::

    python -m scripts.arch_scan [--json] [--root PATH] [--tests-unit PATH]

A scan never decides pass or fail on its own. It reports a count and a list of findings; the
tests in ``tests/test_arch_scan.py`` decide what a passing count is.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator
from pathlib import Path

#: The eight scan names, in the order of spec section 8 (gate 3). The CLI's --json output uses
#: this order for its keys, and the plain-text output prints them in this order too.
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

_DICT_TYPE_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_OS_ENV_ATTRS = frozenset({"environ", "getenv"})
_DOTENV_ATTRS = frozenset({"load_dotenv", "dotenv_values"})
_FAMILY_PREFIX_SUFFIXES = (
    "application.use_cases.",
    "application.models.requests.",
    "application.models.responses.",
)


# =================================================================================================
# Shared filesystem / AST helpers
# =================================================================================================


def _iter_py_files(root: Path, *, under: str | None = None) -> Iterator[Path]:
    """Yield every ``.py`` file under ``root`` (optionally scoped to a subdirectory), sorted."""
    base = root / under if under else root
    if not base.is_dir():
        return
    yield from sorted(p for p in base.rglob("*.py") if p.is_file())


def _rel(root: Path, file: Path) -> str:
    """The POSIX path of ``file`` relative to ``root``, the form every finding reports."""
    return file.relative_to(root).as_posix()


def _parse(file: Path) -> ast.Module | None:
    """Parse ``file`` as Python source, or ``None`` when it cannot be read or parsed.

    A scan is a static best-effort read, not a build gate -- a file it cannot parse is skipped
    rather than raised, since raising here would turn one bad file into a crash for every scan.
    """
    try:
        source = file.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return ast.parse(source, filename=str(file))
    except SyntaxError:
        return None


def _dotted_name(root: Path, file: Path) -> str:
    """The absolute dotted module name of ``file``, with ``root.name`` as the top package.

    ``src/app/infrastructure/kissflow/flow.py`` under root ``src/app`` becomes
    ``app.infrastructure.kissflow.flow``. An ``__init__.py`` names its own package, not a
    ``.__init__`` submodule.
    """
    pkg = root.name
    parts = list(file.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([pkg, *parts]) if parts else pkg


def _own_package(dotted: str, *, is_init: bool) -> str:
    """The dotted package a module's relative imports (``from . import x``) resolve against."""
    if is_init:
        return dotted
    return dotted.rsplit(".", 1)[0] if "." in dotted else ""


def _resolve_relative_import(own_package: str, level: int, module: str | None) -> str:
    """Resolve an ``ast.ImportFrom`` with ``level >= 1`` to an absolute dotted module name.

    Mirrors Python's own relative-import resolution: ``level=1`` resolves against
    ``own_package`` itself, and each extra level drops one more trailing segment of it.
    """
    parts = own_package.split(".") if own_package else []
    cut = level - 1
    if cut > 0:
        parts = parts[:-cut] if cut < len(parts) else []
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _import_from_target(dotted: str, node: ast.ImportFrom, *, is_init: bool) -> str:
    """The absolute dotted module an ``ImportFrom`` imports from (``X`` in ``from X import a``)."""
    if node.level == 0:
        return node.module or ""
    return _resolve_relative_import(
        _own_package(dotted, is_init=is_init), node.level, node.module
    )


def _module_file(root: Path, dotted: str) -> Path | None:
    """The source file a dotted module name resolves to under ``root``, or ``None``.

    Tries ``<path>.py`` first, then ``<path>/__init__.py`` for a package.
    """
    pkg = root.name
    if dotted != pkg and not dotted.startswith(pkg + "."):
        return None
    rest = [p for p in dotted[len(pkg) :].split(".") if p] if dotted != pkg else []
    if rest:
        candidate = root.joinpath(*rest).with_suffix(".py")
        if candidate.is_file():
            return candidate
    pkg_init = root.joinpath(*rest, "__init__.py")
    return pkg_init if pkg_init.is_file() else None


def _module_level_classes(tree: ast.Module) -> list[ast.ClassDef]:
    """Every ``class`` defined directly in the module body (not nested in a function)."""
    return [n for n in tree.body if isinstance(n, ast.ClassDef)]


def _base_name(node: ast.expr) -> str | None:
    """The trailing name of a base-class expression: a ``Name``'s id, or an ``Attribute``'s attr."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# =================================================================================================
# 1. env_reads_outside_settings
# =================================================================================================


def env_reads_outside_settings(root: Path) -> list[str]:
    """Every source line under ``root`` that reads an environment variable outside
    ``infrastructure/config/settings.py`` (spec section 8; the one reader once G2 lands).

    Args:
        root: The package directory to scan, such as ``src/app``.

    Returns:
        Sorted ``"<rel>:<line>"`` findings, one per source line carrying a qualifying read.
    """
    excluded = "infrastructure/config/settings.py"
    findings: list[str] = []
    for file in _iter_py_files(root):
        rel = _rel(root, file)
        if rel == excluded:
            continue
        tree = _parse(file)
        if tree is None:
            continue
        os_aliases: set[str] = set()
        os_direct: set[str] = set()
        dotenv_aliases: set[str] = set()
        dotenv_direct: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "os":
                        os_aliases.add(alias.asname or alias.name)
                    elif alias.name.startswith("os.") and alias.asname is None:
                        # `import os.<sub>` with no `as` name binds the plain name `os`, not
                        # `os.<sub>` -- Python's own import semantics for a dotted import.
                        os_aliases.add("os")
                    elif alias.name == "dotenv":
                        dotenv_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "os":
                    os_direct.update(
                        a.asname or a.name
                        for a in node.names
                        if a.name in _OS_ENV_ATTRS
                    )
                elif node.module == "dotenv":
                    dotenv_direct.update(
                        a.asname or a.name
                        for a in node.names
                        if a.name in _DOTENV_ATTRS
                    )
        lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id in os_aliases and node.attr in _OS_ENV_ATTRS) or (
                    node.value.id in dotenv_aliases and node.attr in _DOTENV_ATTRS
                ):
                    lines.add(node.lineno)
            elif isinstance(node, ast.Name) and (
                node.id in os_direct or node.id in dotenv_direct
            ):
                lines.add(node.lineno)
        findings.extend(f"{rel}:{line}" for line in lines)
    return sorted(findings)


# =================================================================================================
# 2. module_level_fastmcp
# =================================================================================================


class _FastMCPModuleLevelVisitor(ast.NodeVisitor):
    """Finds ``FastMCP(...)`` calls that run at import time: everything except the inside of a
    function or lambda BODY.

    A class-body call (a module-level class's own body, not a method inside it) is still at
    module level. So is a function's decorator list, its parameter defaults, and its return
    annotation -- Python evaluates all three when the ``def``/``lambda`` statement itself runs,
    at the ENCLOSING depth, not when the function is later called. Only the body is a real
    nested scope for this scan's purpose, so only the body visits one level deeper.
    """

    def __init__(self) -> None:
        self.lines: list[int] = []
        self._depth = 0

    def _visit_at_current_depth(self, nodes: Iterator[ast.expr | None]) -> None:
        for node in nodes:
            if node is not None:
                self.visit(node)

    def _visit_one_level_deeper(self, nodes: Iterator[ast.AST]) -> None:
        self._depth += 1
        for node in nodes:
            self.visit(node)
        self._depth -= 1

    def _visit_function_like(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self._visit_at_current_depth(iter(node.decorator_list))
        self._visit_at_current_depth(
            iter([*node.args.defaults, *node.args.kw_defaults])
        )
        self._visit_at_current_depth(iter([node.returns]))
        self._visit_one_level_deeper(iter(node.body))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function_like(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function_like(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self._visit_at_current_depth(
            iter([*node.args.defaults, *node.args.kw_defaults])
        )
        self._visit_one_level_deeper(iter([node.body]))

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self._depth == 0:
            name = _base_name(node.func)
            if name == "FastMCP":
                self.lines.append(node.lineno)
        self.generic_visit(node)


def module_level_fastmcp(root: Path) -> list[str]:
    """Every ``FastMCP(...)`` call under ``root`` that sits outside any function or lambda body.

    Args:
        root: The package directory to scan.

    Returns:
        Sorted ``"<rel>:<line>"`` findings.
    """
    findings: list[str] = []
    for file in _iter_py_files(root):
        tree = _parse(file)
        if tree is None:
            continue
        visitor = _FastMCPModuleLevelVisitor()
        visitor.visit(tree)
        rel = _rel(root, file)
        findings.extend(f"{rel}:{line}" for line in visitor.lines)
    return sorted(findings)


# =================================================================================================
# 3. iserror_dicts
# =================================================================================================


def _docstring_constant_ids(tree: ast.Module) -> set[int]:
    """``id()`` of every string-constant node that IS a module, class, or function docstring.

    A docstring is the first statement of a module/class/function body, when that statement is
    a bare string-literal expression -- the same rule :func:`ast.get_docstring` uses. Identified
    by ``id()`` (object identity) rather than by position, so a comment (not an AST node at all)
    can never collide with one, and the same string appearing again as a real value is untouched.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def iserror_dicts(root: Path) -> list[str]:
    """Every string-constant node under ``root`` whose value is exactly ``"isError"``.

    A comment never matches -- it is not an AST node at all. A module, class, or function
    docstring never matches either, even when its whole text happens to be exactly ``"isError"``
    -- a docstring is excluded by identity, not by guessing at its content.

    Args:
        root: The package directory to scan.

    Returns:
        Sorted ``"<rel>:<line>"`` findings; two such nodes on one line give two findings.
    """
    findings: list[str] = []
    for file in _iter_py_files(root):
        tree = _parse(file)
        if tree is None:
            continue
        rel = _rel(root, file)
        docstring_ids = _docstring_constant_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value == "isError"
                and id(node) not in docstring_ids
            ):
                findings.append(f"{rel}:{node.lineno}")
    return sorted(findings)


# =================================================================================================
# 4. adapter_methods_without_port
# =================================================================================================


def adapter_methods_without_port(root: Path) -> list[str]:
    """Every public method on an ``infrastructure/`` adapter class not named after one of its
    port base's own methods (spec section 8). A class with no port base flags every public
    method it has.

    Scope excludes ``infrastructure/mcp/`` and ``infrastructure/config/`` -- the MCP edge and
    the settings module are not adapters.

    Args:
        root: The package directory to scan.

    Returns:
        Sorted ``"<rel>:<Class>.<method>"`` findings.
    """
    findings: list[str] = []
    prefix = f"{root.name}.application.interfaces."
    bare_pkg = prefix.rstrip(".")
    for file in _iter_py_files(root, under="infrastructure"):
        rel_parts = file.relative_to(root).parts
        if len(rel_parts) >= 2 and rel_parts[1] in {"mcp", "config"}:
            continue
        tree = _parse(file)
        if tree is None:
            continue
        dotted = _dotted_name(root, file)
        is_init = file.name == "__init__.py"
        port_methods_by_bound_name: dict[str, set[str]] = {}
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _import_from_target(dotted, node, is_init=is_init)
            if not target or not (target == bare_pkg or target.startswith(prefix)):
                continue
            target_file = _module_file(root, target)
            if target_file is None:
                continue
            target_tree = _parse(target_file)
            if target_tree is None:
                continue
            target_classes = {c.name: c for c in _module_level_classes(target_tree)}
            for alias in node.names:
                port_class = target_classes.get(alias.name)
                if port_class is None:
                    continue
                bound = alias.asname or alias.name
                port_methods_by_bound_name[bound] = {
                    n.name
                    for n in port_class.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
        rel = _rel(root, file)
        for cls in _module_level_classes(tree):
            port_names: set[str] = set()
            for base in cls.bases:
                base_name = _base_name(base)
                if base_name in port_methods_by_bound_name:
                    port_names |= port_methods_by_bound_name[base_name]
            for member in cls.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if member.name.startswith("_"):
                    continue
                if member.name not in port_names:
                    findings.append(f"{rel}:{cls.name}.{member.name}")
    return sorted(findings)


# =================================================================================================
# 5. port_methods_without_use_case
# =================================================================================================


def _has_abstractmethod(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when one of ``node``'s decorators is ``abstractmethod``, bare or as an attribute."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "abstractmethod":
            return True
    return False


def port_methods_without_use_case(root: Path) -> list[str]:
    """Every ``@abstractmethod`` in a class under ``application/interfaces/`` that no module
    under ``application/use_cases/`` ever references as an attribute (spec section 8).

    Args:
        root: The package directory to scan.

    Returns:
        Sorted ``"<rel>:<Class>.<method>"`` findings.
    """
    used_names: set[str] = set()
    for file in _iter_py_files(root, under="application/use_cases"):
        tree = _parse(file)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used_names.add(node.attr)

    findings: list[str] = []
    for file in _iter_py_files(root, under="application/interfaces"):
        tree = _parse(file)
        if tree is None:
            continue
        rel = _rel(root, file)
        for cls in _module_level_classes(tree):
            for member in cls.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _has_abstractmethod(member):
                    continue
                if member.name not in used_names:
                    findings.append(f"{rel}:{cls.name}.{member.name}")
    return sorted(findings)


# =================================================================================================
# 6. tool_module_imports_own_family_only
# =================================================================================================


def _family_of(candidate: str, pkg: str) -> str | None:
    """The tool family a dotted module candidate names, or ``None`` when it names none."""
    for suffix in _FAMILY_PREFIX_SUFFIXES:
        prefix = f"{pkg}.{suffix}"
        if candidate.startswith(prefix):
            rest = candidate[len(prefix) :]
            if rest:
                return rest.split(".")[0]
    return None


def _record_family_hit(
    hits: set[tuple[int, str]], lineno: int, candidate: str, pkg: str, own_family: str
) -> None:
    """Add ``(lineno, family)`` to ``hits`` when ``candidate`` names a family other than
    ``own_family``."""
    family = _family_of(candidate, pkg)
    if family is not None and family != own_family:
        hits.add((lineno, family))


def tool_module_imports_own_family_only(root: Path) -> list[str]:
    """Every import in an ``infrastructure/mcp/tools/<family>.py`` module that names a tool
    family other than its own (spec section 8, D5's one-module-per-family rule).

    Args:
        root: The package directory to scan.

    Returns:
        Sorted ``"<rel>:<line>:<other_family>"`` findings, once per line and family.
    """
    tools_dir = root / "infrastructure" / "mcp" / "tools"
    findings: list[str] = []
    if not tools_dir.is_dir():
        return findings
    pkg = root.name
    for file in sorted(tools_dir.glob("*.py")):
        if file.name == "__init__.py":
            continue
        own_family = file.stem
        tree = _parse(file)
        if tree is None:
            continue
        dotted = _dotted_name(root, file)
        own_package = _own_package(dotted, is_init=False)
        rel = _rel(root, file)
        hits: set[tuple[int, str]] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _record_family_hit(hits, node.lineno, alias.name, pkg, own_family)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    target = _resolve_relative_import(
                        own_package, node.level, node.module
                    )
                else:
                    target = node.module or ""
                for alias in node.names:
                    _record_family_hit(hits, node.lineno, target, pkg, own_family)
                    combined = f"{target}.{alias.name}" if target else alias.name
                    _record_family_hit(hits, node.lineno, combined, pkg, own_family)
        findings.extend(f"{rel}:{lineno}:{family}" for lineno, family in hits)
    return sorted(findings)


# =================================================================================================
# 7. tests_mirror_src
# =================================================================================================


def tests_mirror_src(root: Path, tests_unit: Path) -> list[str]:
    """Every non-``__init__`` module under ``root`` with no mirror test under ``tests_unit``.

    The mirror of ``root/<parent>/<name>.py`` is ``tests_unit/<parent>/test_<name>.py``.

    Args:
        root: The package directory to scan, such as ``src/app``.
        tests_unit: The unit-test tree that should mirror ``root`` one to one.

    Returns:
        Sorted ``"<rel>"`` findings: the source files with no mirror.
    """
    findings: list[str] = []
    for file in _iter_py_files(root):
        if file.name == "__init__.py":
            continue
        rel_path = file.relative_to(root)
        mirror = tests_unit / rel_path.parent / f"test_{file.name}"
        if not mirror.is_file():
            findings.append(rel_path.as_posix())
    return sorted(findings)


# =================================================================================================
# 8. dict_draft_in_domain_api
# =================================================================================================

_EXCLUDED_METHOD_NAMES = frozenset({"from_wire", "to_wire"})


def _resolve_string_annotation(node: ast.expr | None) -> ast.expr | None:
    """Parse a string-literal annotation into its expression tree; pass any other node through."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return node
    return node


def _is_dict_type(node: ast.expr | None) -> bool:
    """True when ``node`` structurally names a dict type: bare, subscripted, or an attribute
    (``dict``, ``Dict``, ``Mapping``, ``MutableMapping``, or ``typing.Dict`` and friends)."""
    resolved = _resolve_string_annotation(node)
    if isinstance(resolved, ast.Subscript):
        resolved = resolved.value
    if isinstance(resolved, ast.Name):
        return resolved.id in _DICT_TYPE_NAMES
    if isinstance(resolved, ast.Attribute):
        return resolved.attr in _DICT_TYPE_NAMES
    return False


def _annotation_names(node: ast.expr | None) -> set[str]:
    """Every ``Name`` id and ``Attribute`` attr reachable from an annotation expression,
    resolving nested string-literal forward references along the way."""
    names: set[str] = set()
    if node is None:
        return names
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Name):
            names.add(current.id)
        elif isinstance(current, ast.Attribute):
            names.add(current.attr)
            stack.append(current.value)
        elif isinstance(current, ast.Constant) and isinstance(current.value, str):
            resolved = _resolve_string_annotation(current)
            if resolved is not None and resolved is not current:
                stack.append(resolved)
        else:
            stack.extend(ast.iter_child_nodes(current))
    return names


def _alias_target(node: ast.stmt) -> tuple[str | None, ast.expr | None]:
    """The ``(name, value)`` a module-level Assign/AnnAssign/``type X = ...`` statement defines."""
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id, node.value
    if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
        return node.name.id, node.value
    return None, None


def _all_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    """Every parameter of a function, positional-only through ``**kwargs``."""
    params = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg:
        params.append(node.args.vararg)
    if node.args.kwarg:
        params.append(node.args.kwarg)
    return params


def _flags_dict_draft(
    node: ast.FunctionDef | ast.AsyncFunctionDef, draft_aliases: set[str]
) -> bool:
    """True when ``node`` matches rule (a) or (b) of ``dict_draft_in_domain_api``."""
    params = _all_params(node)
    for ann in [p.annotation for p in params] + [node.returns]:
        if _annotation_names(ann) & draft_aliases:
            return True
    for p in params:
        if (p.arg == "draft" or p.arg.endswith("_draft")) and _is_dict_type(
            p.annotation
        ):
            return True
    return False


def dict_draft_in_domain_api(root: Path) -> list[str]:
    """Every public function or method under ``domain/`` whose parameters or return type still
    take a bare dict draft, rather than a rich entity (spec section 8; the target shape G9 moves
    domain/ to).

    Args:
        root: The package directory to scan.

    Returns:
        Sorted ``"<rel>:<qualname>"`` findings (``func`` for a function, ``Class.method`` for a
        method).
    """
    trees: dict[Path, ast.Module] = {}
    draft_aliases: set[str] = set()
    for file in _iter_py_files(root, under="domain"):
        tree = _parse(file)
        if tree is None:
            continue
        trees[file] = tree
        for node in tree.body:
            name, value = _alias_target(node)
            if name is not None and name.endswith("Draft") and _is_dict_type(value):
                draft_aliases.add(name)

    findings: list[str] = []
    for file, tree in trees.items():
        rel = _rel(root, file)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_") and _flags_dict_draft(
                    node, draft_aliases
                ):
                    findings.append(f"{rel}:{node.name}")
            elif isinstance(node, ast.ClassDef):
                for member in node.body:
                    if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if (
                        member.name.startswith("_")
                        or member.name in _EXCLUDED_METHOD_NAMES
                    ):
                        continue
                    if _flags_dict_draft(member, draft_aliases):
                        findings.append(f"{rel}:{node.name}.{member.name}")
    return sorted(findings)


# =================================================================================================
# CLI
# =================================================================================================


def run_all(root: Path, tests_unit: Path) -> dict[str, list[str]]:
    """Run every scan once, in spec section 8 order.

    Args:
        root: The package directory to scan, such as ``src/app``.
        tests_unit: The unit-test tree ``tests_mirror_src`` checks against.

    Returns:
        A dict from scan name to its findings, keyed in ``SCAN_NAMES`` order.
    """
    return {
        "env_reads_outside_settings": env_reads_outside_settings(root),
        "module_level_fastmcp": module_level_fastmcp(root),
        "iserror_dicts": iserror_dicts(root),
        "adapter_methods_without_port": adapter_methods_without_port(root),
        "port_methods_without_use_case": port_methods_without_use_case(root),
        "tool_module_imports_own_family_only": tool_module_imports_own_family_only(
            root
        ),
        "tests_mirror_src": tests_mirror_src(root, tests_unit),
        "dict_draft_in_domain_api": dict_draft_in_domain_api(root),
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m scripts.arch_scan``.

    Args:
        argv: Argument vector to parse instead of ``sys.argv[1:]``, for tests.

    Returns:
        Always ``0`` when the scans ran. A scan never decides pass or fail; a caller (a test)
        does that by reading the counts and findings this prints.
    """
    parser = argparse.ArgumentParser(prog="python -m scripts.arch_scan")
    parser.add_argument(
        "--json", action="store_true", help="print one JSON object instead of text"
    )
    parser.add_argument(
        "--root", default="src/app", help="the package directory to scan"
    )
    parser.add_argument(
        "--tests-unit",
        default="tests/unit",
        help="the unit-test tree tests_mirror_src checks",
    )
    args = parser.parse_args(argv)
    root = Path(args.root)
    tests_unit = Path(args.tests_unit)
    results = run_all(root, tests_unit)

    if args.json:
        payload = {
            name: {"count": len(findings), "findings": findings}
            for name, findings in results.items()
        }
        print(json.dumps(payload, indent=2))
    else:
        for name, findings in results.items():
            print(f"{name}: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
