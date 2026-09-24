"""Closed vocabularies shared by the Kissflow builder API's ports, adapters and tools.

Every `Literal` alias here used to be defined twice: once in
`infrastructure/kissflow/client.py` (the flow-shaped kinds) and once in
`infrastructure/mcp/server.py` (the MCP-boundary enums). Both modules now
import from here instead, so the tool schema and the port signatures can
never drift apart by editing one copy and not the other. Domain-layer rules
apply: stdlib only, no I/O, no third-party imports (`code_architecture.md`).
"""

from __future__ import annotations

from typing import Literal

# The three real FLOW kinds. Used by every method whose `kind` reaches a
# `/flow` or `/metadata` draft URL AND whose surface (workflow / permissions
# / members / publish) exists on that kind.
FlowKind = Literal["form", "process", "case"]

# A draft-carrying flow OR a page: the draft-read surface. A page draft lives
# under its owning application, so "page" additionally requires an app id,
# enforced by the caller, since a closed literal cannot express it.
SchemaKind = Literal["form", "process", "case", "dataset", "page"]

# `FlowKind` re-exported under the name the MCP tool boundary historically
# used. The two must name the same three strings, so this stays a plain
# alias rather than a second definition.
FlowKindArg = FlowKind

# Has a field-bearing draft graph. Adds "dataset": field writes there
# produce the identical node shapes as a flow's own draft
# (docs/capabilities/module.dataform.md, #50). A word list is excluded — it
# has no draft graph to write fields into.
DataKind = Literal["form", "process", "case", "dataset"]

# Anything addressable at a /flow or /metadata URL. `kind` is interpolated
# into the path segment and only branched on for `== "process"`, so the
# read/list/create/delete methods genuinely take all five.
AnyFlowKind = Literal["form", "process", "case", "list", "dataset"]

# What `delete_anything`/`FlowRepository.delete_flow` can actually delete —
# NOT the same set as `PublishKind`. `list` and `dataset` fall through to
# the generic `/flow/2/{acct}/{kind}` delete route; only `process` archives
# first (400 KISSFLOW_ERROR_04602 otherwise).
DeleteKind = Literal[
    "form", "process", "case", "list", "dataset", "page", "application"
]

# Everything that can be compiled to a live version: the three flow kinds
# with a draft/live split, plus the two container kinds that have their own
# publish routes. `list` and `dataset` are deliberately ABSENT — both are
# born LIVE with no publish route at all.
PublishKind = Literal["form", "process", "case", "page", "application"]

# `create_flow_any`'s wider set: list/dataset/case are born LIVE (no publish
# step), process/form start as a Draft.
CreateFlowKind = Literal["process", "form", "list", "dataset", "case"]

# The permission-TIER ladder is flow-type-dependent: only process and case
# have one at all.
TierKind = Literal["process", "case"]
Tier = Literal["No access", "Initiate", "Read-only", "Edit", "Manage"]

# The dataform record data plane's `op` values. A fifth string would be
# interpolated into the route and 404 against a live tenant.
DatasetOp = Literal["create", "update", "delete", "list"]

# The sweep-scope fan-out, plus the "all" alias.
SweepScope = Literal["apps", "flows", "pages", "roles", "lists", "all"]

# `design.confirm.is_approved` accepts exactly one literal and nothing
# else — not "Approve", not "approved", not a revise request.
ApprovalDecision = Literal["approve"]

# The skills `forge_playbook` serves over the MCP, one vendored SKILL.md each:
# builder = the build order, design = the business-owner interview,
# usage = how to drive this MCP. Closed so no caller string reaches a path.
PlaybookName = Literal["builder", "design", "usage"]
