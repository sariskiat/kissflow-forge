"""kfforge.intake.serde -- exact dict round-trip for AppSpec: the wire format a stateless MCP
tool passes in and returns on every call, since the server itself holds no session state
(kfforge/server.py's forge_* intake/design tools take a spec dict as an argument and hand a spec
dict back -- there is nowhere else for the spec to live between two calls).

`spec_to_dict`/`spec_from_dict` are driven entirely by `AppSpec`'s own dataclass field type hints
(`typing.get_type_hints`, resolved against `kfforge.intake.schema`'s module globals, since every
annotation in that module is a postponed string under `from __future__ import annotations`) --
there is no second, hand-maintained shape description here to drift out of sync with the schema.
Enums serialize by `.value` (`FieldType`/`Visibility`/`EventTrigger` are all `StrEnum`, so this is
mostly cosmetic at the JSON-text level, but it is done explicitly rather than relied on as an
accident of `StrEnum` also being a `str` subclass). A tuple-of-pairs field (`route_per_option`,
`options`, `config`, `values` on `StepFill`, ...) is `kfforge.intake.schema`'s OWN on-wire shape
already -- a plain tuple of 2-tuples, chosen there specifically so a frozen dataclass never needs
a mutable `dict` field (see that module's own docstring) -- so no special-casing is needed here
beyond the generic tuple -> list conversion every tuple gets: each pair becomes an ordinary
2-element list, exactly the shape `dict(pairs).items()` would produce, without this module ever
needing to know "which fields are mapping-shaped."

`to_wire` (the one-way, forward-only half of this) is exported separately from `spec_to_dict`
because `kfforge.server` needs the exact same dataclass/enum/tuple -> JSON-safe conversion for
OTHER dataclasses this package hands back from a tool call (`kfforge.intake.compile.BuildPlan`/
`Op`, `kfforge.design.ConfirmationRequest`, `kfforge.intake.questions.Question`) without ever
needing to parse one of THOSE back out of JSON -- only `AppSpec` round-trips, so only `AppSpec`
gets a reverse direction (`_from_wire` is kept private: nothing outside this module needs to
reconstruct an arbitrary dataclass from JSON, only a real `AppSpec`).

Malformed input never drops a dimension silently. A missing required key, an unknown key, or a
value that fails to match its field's real type all raise `ValueError` naming the exact dotted/
indexed PATH to the offending piece (e.g. `"AppSpec.data_model.fields[2].type"`) -- a caller
mis-typing or omitting one key sees precisely which one, rather than receiving a spec that quietly
falls back to an empty dimension, which would then look exactly like a gap the customer never
actually answered (the same silent-drop failure `kfforge.intake.schema`'s own docstring warns
`AppSpec.gaps()` must never produce).
"""
from __future__ import annotations

import dataclasses
import enum
import functools
import types
import typing
from collections.abc import Mapping
from typing import Any

from .schema import AppSpec

__all__ = ["spec_from_dict", "spec_to_dict", "to_wire"]

_UNION_ORIGINS = (typing.Union, types.UnionType)  # `X | None` (PEP 604) and `Optional[X]` both


# -------------------------------------------------------------------------------------------
# to_wire: generic, one-way, dataclass/enum/tuple/list/dict/scalar -> JSON-safe structure. No
# target type is needed (it inspects the VALUE, not a declared shape), so it also serializes
# non-AppSpec dataclasses this package hands back from a tool (BuildPlan, Op, ConfirmationRequest,
# Question) -- see this module's own docstring for why those never need the reverse direction.
# -------------------------------------------------------------------------------------------


def to_wire(value: Any) -> Any:
    """JSON-safe snapshot of any dataclass/enum/tuple/list/dict/scalar tree. Enums become their
    `.value`; tuples and lists both become plain lists; dataclasses become plain dicts, field by
    field, via `dataclasses.fields` (never a second, hand-written field list to drift out of sync
    with a schema); dict keys are coerced to `str` (every dict this package ever produces already
    uses string keys -- `kfforge.intake.compile.Op.args` -- this is defensive, not load-bearing).
    Anything else (a value this package's own dataclasses never actually hold) raises rather than
    being silently dropped or stringified into something that looks like real data.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_wire(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): to_wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_wire(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError(f"cannot serialize value of type {type(value).__name__}: {value!r}")


# -------------------------------------------------------------------------------------------
# spec_from_dict: the one direction that NEEDS a target shape, because JSON alone cannot tell a
# tuple-of-pairs from a same-length tuple-of-tuples that just happens to hold two strings, or a
# plain string from an enum's wire value -- AppSpec's own dataclass field type hints supply that
# shape, so this module never has to guess.
# -------------------------------------------------------------------------------------------


@functools.lru_cache
def _field_types(cls: type) -> Mapping[str, Any]:
    """Field name -> resolved (real, not string) type annotation for a dataclass, via
    `typing.get_type_hints`. Needed because `kfforge.intake.schema` (like this module) writes
    `from __future__ import annotations`, so `dataclasses.fields(cls)[i].type` is a plain
    unevaluated string and cannot be introspected (`typing.get_origin`/`get_args`) directly.

    Cached: `cls` is one of a small, fixed set of dataclasses in `AppSpec`'s own tree (~28 total),
    and `typing.get_type_hints(cls)` is a pure function of the class OBJECT (never of any
    per-call value passed through `_from_wire`) — safe to memoize with no invalidation concern,
    and worth it: `spec_from_dict` re-resolves hints for the SAME classes on every field of every
    element of every tuple in a spec, so this was measured re-running `typing.get_type_hints` for
    the same class dozens of times per call on a dense spec.

    Returns a `types.MappingProxyType` view, not a plain `dict` — `lru_cache` hands back the exact
    same object on every hit, so a plain dict would let any future call site mutate the SHARED
    cached value for every other caller (every call site today only reads it, so this was not yet
    a live bug — a read-only view removes the hazard structurally rather than trusting that
    convention holds forever).
    """
    hints = typing.get_type_hints(cls)
    return types.MappingProxyType({f.name: hints[f.name] for f in dataclasses.fields(cls)})


def _has_default(cls: type, name: str) -> bool:
    for f in dataclasses.fields(cls):
        if f.name == name:
            return f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
    raise KeyError(name)  # pragma: no cover -- only ever called with a name _field_types just gave us


def _from_wire(value: Any, typ: Any, *, path: str) -> Any:
    origin = typing.get_origin(typ)

    if origin in _UNION_ORIGINS:
        args = typing.get_args(typ)
        if value is None:
            if type(None) in args:
                return None
            raise ValueError(f"{path}: got null, which {typ!r} does not allow")
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) != 1:
            raise ValueError(f"{path}: unsupported union type {typ!r} (only 'T | None' is handled)")
        return _from_wire(value, non_none[0], path=path)

    if dataclasses.is_dataclass(typ):
        if not isinstance(value, dict):
            raise ValueError(
                f"{path}: expected an object for {typ.__name__}, got {type(value).__name__}"
            )
        field_types = _field_types(typ)
        unknown = sorted(set(value) - set(field_types))
        if unknown:
            raise ValueError(f"{path}: unknown key(s) {unknown} for {typ.__name__}")
        kwargs: dict[str, Any] = {}
        for name, ftyp in field_types.items():
            if name in value:
                kwargs[name] = _from_wire(value[name], ftyp, path=f"{path}.{name}")
            elif not _has_default(typ, name):
                raise ValueError(f"{path}.{name}: missing required key")
        return typ(**kwargs)

    if isinstance(typ, type) and issubclass(typ, enum.Enum):
        try:
            return typ(value)
        except ValueError:
            legal = ", ".join(repr(m.value) for m in typ)
            raise ValueError(
                f"{path}: {value!r} is not a valid {typ.__name__} (legal values: {legal})"
            ) from None

    if origin is tuple:
        if not isinstance(value, list):
            raise ValueError(f"{path}: expected a list for a tuple field, got {type(value).__name__}")
        args = typing.get_args(typ)
        if len(args) == 2 and args[1] is Ellipsis:
            elem_type = args[0]
            return tuple(_from_wire(v, elem_type, path=f"{path}[{i}]") for i, v in enumerate(value))
        if len(value) != len(args):
            raise ValueError(f"{path}: expected {len(args)} element(s), got {len(value)}")
        return tuple(
            _from_wire(v, t, path=f"{path}[{i}]") for i, (v, t) in enumerate(zip(value, args))
        )

    if typ is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{path}: expected bool, got {type(value).__name__}: {value!r}")
        return value
    if typ in (str, int, float):
        if not isinstance(value, typ) or isinstance(value, bool):
            raise ValueError(f"{path}: expected {typ.__name__}, got {type(value).__name__}: {value!r}")
        return value

    raise ValueError(f"{path}: unsupported type annotation {typ!r}")  # pragma: no cover -- every
    # branch AppSpec's own tree actually uses is handled above; this only guards a future field
    # whose shape this module has not been taught yet, so it fails loud instead of mis-parsing it.


def spec_to_dict(spec: AppSpec) -> dict[str, Any]:
    """`AppSpec` -> a plain, `json.dumps`-able dict. See `to_wire` for the general mechanism."""
    return to_wire(spec)


def spec_from_dict(data: dict[str, Any]) -> AppSpec:
    """The inverse of `spec_to_dict`, exact: `spec_from_dict(spec_to_dict(s)) == s` for any real
    `AppSpec` (proven in tests/test_serde.py). Raises `ValueError` naming the exact path of the
    first missing/unknown/mistyped key; never silently drops or defaults a whole dimension.
    """
    if not isinstance(data, dict):
        # ValueError, not TypeError (ruff TRY004 below) — every raise in this module is a
        # ValueError for "this value is not what the wire format requires" (matching
        # kfforge.intake.compile's own precedent, same rule suppressed the same way there); a
        # top-level non-dict is that SAME class of problem, not a Python-level type error.
        raise ValueError(f"AppSpec: expected an object, got {type(data).__name__}")  # noqa: TRY004
    return _from_wire(data, AppSpec, path="AppSpec")
