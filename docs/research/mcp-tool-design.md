# MCP tool-design best practices for agent usability

Research for ticket **#54** ("MCP tool-design best practices for agent usability"),
part of wayfinder map **#42**. This is primary-source research only — no code
changes. It gathers what the state of the art says about designing tools an LLM
agent invokes reliably, and closes with concrete implications for kissflow-forge's
own MCP surface (`kfforge/server.py`), feeding directly into follow-on ticket
**#55** ("MCP-surface-design").

All dated citations below were fetched live on 2026-08-12 unless the source
itself states a different publish date.

---

## 1. Principles for designing tools LLM agents invoke reliably

**Treat the tool contract like a human-computer interface, then go further.**
Anthropic's foundational framing: tools are "a contract between deterministic
systems and non-deterministic agents" — unlike a normal API, the caller can
misread, hallucinate, or misuse the interface, so the interface itself has to
absorb that risk (Anthropic, "Writing effective tools for AI agents", Sept 11
2025, https://www.anthropic.com/engineering/writing-tools-for-agents). The
earlier "Building effective agents" post frames this as an **agent-computer
interface (ACI)**, deserving the same design rigor as a human-computer
interface: "Put yourself in the model's shoes. Is it obvious how to use this
tool, based on the description and parameters, or would you need to think
carefully about it?" (Anthropic, "Building Effective Agents", Dec 19 2024,
https://www.anthropic.com/engineering/building-effective-agents).

**Naming.** Parameters must be unambiguous on their own — "instead of a
parameter named `user`, try a parameter named `user_id`" (Anthropic, "Writing
effective tools for AI agents", Sept 11 2025). Namespacing tool names by
service and by resource (e.g. `asana_projects_search` vs `asana_users_search`)
delineates boundaries once a surface has many tools; whether prefix- or
suffix-based namespacing performs better is model-dependent and worth
evaluating per deployment, not assumed (same source).

**Descriptions.** Write a tool description the way you'd brief "a new hire on
your team" — make explicit any context you'd otherwise bring implicitly:
specialized formats, niche terminology, relationships between resources (same
source). "Building effective agents" adds the format-of-least-friction
principle: "Keep the format close to what the model has seen naturally
occurring in text on the internet," avoiding overhead like manual
string-escaping or line-counting that the model has to reconstruct correctly
(Anthropic, "Building Effective Agents", Dec 19 2024).

**Schema design and parameter shape.** Apply *poka-yoke* (mistake-proofing):
restructure parameters "so that it is harder to make mistakes" (same source).
The MCP spec itself formalizes the schema surface a tool exposes: `name`,
optional `title` (a separate display name from the machine-readable `name`),
`description`, `inputSchema` (JSON Schema, with `required` as an explicit
array), and an optional `outputSchema` for structured results — validated
client-side against that schema (Model Context Protocol, "Tools"
specification, 2025-06-18 revision, fetched 2026-08-12,
https://modelcontextprotocol.io/specification/2025-06-18/server/tools).
Anthropic's own guidance for response shape: tools can expose a
`response_format` enum (e.g. `"concise"` vs `"detailed"`) so the same tool
serves both natural-language use and technical/id-chaining use, and response
*structure* itself (XML vs JSON vs Markdown) measurably affects evaluation
performance, with no single winner — it varies by task and agent (Anthropic,
"Writing effective tools for AI agents", Sept 11 2025).

**Iterate against real model behavior, not intuition.** "Run many example
inputs in our workbench to see what mistakes the model makes, and iterate" —
tool design is empirical, the same way this repo's own CLAUDE.md treats the
Kissflow graph shapes as captures, not specs (Anthropic, "Building Effective
Agents", Dec 19 2024).

---

## 2. Few-general-composable vs many-specific tools, and the token cost of tool count

**The core tradeoff, stated directly.** "More tools don't always lead to
better outcomes. A common error we've observed is tools that merely wrap
existing software functionality or API endpoints — whether or not the tools
are appropriate for agents" (Anthropic, "Writing effective tools for AI
agents", Sept 11 2025). The same source gives the operative consolidation
example: instead of `list_users`, `list_events`, and `create_event` as three
separate tools, build one `schedule_event` tool that finds availability and
schedules the event under the hood — "Tools can consolidate functionality,
handling potentially *multiple* discrete operations (or API calls) under the
hood." The stated payoff is double: fewer tool descriptions consume context,
*and* less intermediate output has to round-trip through the model — "Tools
should enable agents to subdivide and solve tasks in much the same way that a
human would... and simultaneously reduce the context that would have
otherwise been consumed by intermediate outputs" (same source).

**Why this matters mechanically: tool definitions cost real, measured
tokens.** Anthropic's context-engineering post is explicit that context is the
scarce resource an agent design has to budget: "One of the most common
failure modes we see is bloated tool sets that cover too much functionality or
lead to ambiguous decision points about which tool to use" (Anthropic,
"Effective context engineering for AI agents", Sept 29 2025,
https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
Anthropic's later "code execution with MCP" post puts a concrete number on
the cost of loading many tool definitions directly into context versus
letting the agent load them progressively as code: a worked example dropped
from 150,000 tokens to 2,000 tokens (a 98.7% reduction) by presenting MCP
tools as files on a filesystem the model reads on demand rather than as a
flat, always-loaded tool list — "Presenting tools as code on a filesystem
allows models to read tool definitions on-demand, rather than reading them
all up-front" (Anthropic, "Code execution with MCP: building more efficient AI
agents", Nov 4 2025, https://www.anthropic.com/engineering/code-execution-with-mcp).
That same mechanism is what the post says lets an agent scale to "hundreds or
thousands of tools across dozens of MCP servers" without the flat token cost
that a directly-loaded tool list would otherwise impose.

**Selective tool-building is itself a design lever, not just a count
constraint.** "Careful, selective planning of the tools you build (or don't
build) can really pay off... By selectively implementing tools whose names
reflect natural subdivisions of tasks, you simultaneously reduce the number of
tools and tool descriptions loaded into the agent's context" (Anthropic,
"Writing effective tools for AI agents", Sept 11 2025) — i.e. the "few general"
side of the tradeoff isn't just about token count, it's also about reducing
the number of ambiguous decision points where the model might pick the wrong
tool.

**Net read:** the literature does not argue "many narrow tools are always
wrong" — it argues that raw API-endpoint-wrapping tool proliferation is the
anti-pattern, and that consolidating around natural task subdivisions (not
around raw CRUD operations) is what buys both lower token cost and fewer
ambiguous choices. A small number of well-designed, composable primitives
that map to how a human would actually break down the task is the repeatedly
stated goal — not one giant do-everything tool and not one tool per API call.

---

## 3. Validation and error-message design for model self-correction

**Errors are prompt-engineering surface, not just plumbing.** "If a tool call
raises an error... you can prompt-engineer your error responses to clearly
communicate specific and actionable improvements, rather than opaque error
codes or tracebacks" (Anthropic, "Writing effective tools for AI agents",
Sept 11 2025). The article explicitly contrasts an "unhelpful error response"
(a generic exception) against a "helpful" one that gives specific formatting
guidance and worked examples of correctly-shaped input — the actionable
version tells the model *what to send instead*, not just that something
failed. The same discipline extends to truncation: "Tool truncation and error
responses can steer agents towards more token-efficient tool-use behaviors
(using filters or pagination) or give examples of correctly formatted tool
inputs" (same source) — an error/truncation message is a second chance to
teach the model the interface, not merely a failure signal.

**The protocol layer separates two different kinds of failure, and callers
must handle both.** MCP formalizes this split: **protocol errors** are
standard JSON-RPC errors (unknown tool, invalid arguments, server error,
`-32602`/`-32603`/etc.) that never reach the model as tool output; **tool
execution errors** are reported *inside* a normal tool result with
`isError: true`, so the model actually sees the error text and can act on it
(API failures, invalid input data, business-logic errors) (Model Context
Protocol, "Tools" specification, 2025-06-18, fetched 2026-08-12,
https://modelcontextprotocol.io/specification/2025-06-18/server/tools). A
tool author who wants the model to *self-correct* from a failure has to use
the `isError: true` execution-error path with real natural-language guidance
in the content — a bare protocol error never reaches the model to reason
about at all.

**Validate before writing, and validate against live truth, never a guess.**
This isn't from the external literature but is this repo's own load-bearing,
independently-proven version of the same principle (kissflow-forge CLAUDE.md,
"Expressions" and "Item data plane" sections): a mis-cased literal or an
out-of-list Select value writes fine (HTTP 200), publishes fine, and then
silently never fires or silently clears — the failure is invisible until a
human notices behavior is wrong. The fix pattern already in use here —
validate against the live option list *before* the write, refuse loudly if it
doesn't match — is the same "actionable, not opaque" principle from area 3
applied one level earlier: a validation error caught at write time is
actionable ("here is the real list, your value wasn't in it"); a silent
runtime failure discovered days later is not.

---

## 4. Serving domain knowledge to the model: tool descriptions vs MCP resources vs prompts/skills

MCP formally splits three primitives by **who controls invocation**, which is
the load-bearing distinction for deciding where domain knowledge belongs:

- **Tools are model-controlled.** "The language model can discover and invoke
  tools automatically based on its contextual understanding" (Model Context
  Protocol, "Tools" specification, 2025-06-18, fetched 2026-08-12). Tool
  *descriptions* are where knowledge the model needs at decision time (when
  to call this, what it needs, what it returns) belongs — because that's the
  only domain knowledge guaranteed to be loaded before the model decides to
  act.
- **Resources are application-driven**, not model-driven: "host applications
  determining how to incorporate context based on their needs" — via explicit
  UI selection, search/filter, or automatic inclusion by heuristic (Model
  Context Protocol, "Resources" specification, 2025-06-18, fetched
  2026-08-12, https://modelcontextprotocol.io/specification/2025-06-18/server/resources).
  Resources are the right place for reference data the model (or the host
  app on the model's behalf) pulls in only when relevant — file contents,
  schemas, large reference material — not narrative instructions.
- **Prompts are user-controlled**: "exposed from servers to clients with the
  intention of the user being able to explicitly select them for use,"
  typically surfaced as something like a slash command (Model Context
  Protocol, "Prompts" specification, 2025-06-18, fetched 2026-08-12,
  https://modelcontextprotocol.io/specification/2025-06-18/server/prompts).
  Prompts are for reusable, human-triggered workflow templates — not
  something the agent reaches for autonomously mid-task.

**Anthropic's Skills mechanism is the fourth option for domain
knowledge**, distinct from all three MCP primitives, and it is explicitly
about *procedural* knowledge rather than *data access*: "MCP connects Claude
to data; Skills teach Claude what to do with that data." The dividing
question given: "If you're explaining how to use a tool or follow
procedures... that's a Skill. If you need Claude to access the database or
Excel files in the first place, that's MCP." (Claude/Anthropic, "Skills
explained: How Skills compares to prompts, Projects, MCP, and subagents",
March 5 2026, https://claude.com/blog/skills-explained). Skills also solve the
token-budget problem for domain knowledge directly, via **progressive
disclosure**: "Metadata loads first (~100 tokens)... Full instructions load
when needed (<5k tokens), and bundled files or scripts load only as required"
— so an agent can have access to many skills' worth of domain knowledge
without paying the token cost for all of it up front (same source).

**Context-engineering guidance ties the two data-loading strategies
together.** Loading everything up front is faster per-call but risks
"drowning in exhaustive but potentially irrelevant information"; the
alternative — "just in time" — keeps only lightweight identifiers (paths,
query handles, links) in context and dynamically loads the real data via a
tool call at the moment it's needed, trading some latency for a much smaller
steady-state context footprint; the article's own recommendation is often a
**hybrid**: some data eagerly loaded for speed, deeper exploration left to
the agent's discretion (Anthropic, "Effective context engineering for AI
agents", Sept 29 2025).

**Practical mapping**, synthesizing all of the above:

| Kind of knowledge | Right mechanism |
|---|---|
| "When should I call this, what does it need, what comes back" | Tool `description` / `inputSchema` |
| Large or occasionally-needed reference data (a schema, a captured shape, a big enum) | MCP resource, fetched just-in-time |
| A reusable, human-triggered multi-step workflow | MCP prompt |
| "Here's how this whole domain works, procedurally, loaded only when relevant" | An Anthropic Skill (progressive disclosure) |

---

## 5. Patterns for multi-step build workflows via MCP: state, idempotency, dry-run/confirm

**MCP's formal safety primitive is a set of behavioral hint annotations on
each tool**, introduced in the 2025-03-26 spec revision (PR #185, authored by
Basil Hosmer at Anthropic) and analyzed in depth in a dedicated protocol blog
post: `readOnlyHint` (does it modify anything; default **false**),
`destructiveHint` (if it modifies, is the change destructive/hard-to-undo vs
additive; default **true**), `idempotentHint` (safe to call again with the
same arguments and get the same effect; default **false**), and
`openWorldHint` (does it reach into an open world of external entities, or a
closed domain; default **true**) (Model Context Protocol Blog, "Tool
Annotations as Risk Vocabulary: What Hints Can and Can't Do", March 16 2026,
https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/). The
defaults are deliberately pessimistic — "The spec assumes the worst until the
server says otherwise" — so an unannotated tool is treated as potentially
destructive, non-idempotent, and open-world unless the server explicitly
claims otherwise. The stated client-side use case is exactly a
confirmation gate: "A tool marked `readOnlyHint: true` from a trusted server
might be auto-approved, while `destructiveHint: true` gets a confirmation
step," illustrated with a delete-file example where the client shows a
listing of what's about to be deleted before anything happens (same source).

**Critical caveat: annotations are hints, not enforcement, and must be
treated as untrusted from an untrusted server.** Both the spec itself and the
analysis post are explicit: "annotations are not guaranteed to faithfully
describe tool behavior, and clients **must** treat them as untrusted unless
they come from a trusted server" (Model Context Protocol, "Tools"
specification, 2025-06-18, fetched 2026-08-12); "An untrusted server can lie.
A server can claim `readOnlyHint: true` and delete your files anyway" (Model
Context Protocol Blog, March 16 2026). Annotations "don't make the model
resist prompt injection" and "aren't enforcement" — for a genuine safety
guarantee the same post points to sandboxing or network controls, not a
boolean hint (same source). The spec's own user-interaction guidance for
tools generally reinforces this at the protocol level, independent of
annotations: "there **SHOULD** always be a human in the loop with the ability
to deny tool invocations," and applications **SHOULD** "present confirmation
prompts to the user for operations, to ensure a human is in the loop" (Model
Context Protocol, "Tools" specification, 2025-06-18, fetched 2026-08-12).

**Annotation mismatch is itself a named, catalogued failure mode.** A
dedicated MCP-server security catalogue documents this precisely: "MCP tools
with destructive names or behaviors lack honest annotations, allowing LLM
clients to invoke state-mutating operations silently without user
confirmation" — either a tool named `delete_*`/`wipe_*`/`drop_*` etc. shipped
*without* `destructiveHint: true`, or (worse) a tool that falsely declares
`readOnlyHint: true` while its implementation still performs a destructive
write. The stakes are stated plainly: "the LLM selects and invokes tools
autonomously based on tool names, descriptions, and annotations — meaning a
missing or false annotation directly determines whether the model executes a
destructive action without any confirmation gate" (MCPSafe, "Destructive Tool
Annotation Mismatch in MCP Servers", © 2026, fetched 2026-08-12,
https://mcpsafe.io/threats/MCP-200). This is a non-Anthropic secondary
source, included because it independently reinforces the MCP-primary
annotation guidance in the block above (area 5, MCP Blog March 16 2026): the
annotation is only as trustworthy as the implementation behind it, and a
mismatch is a documented, exploitable class of bug, not a hypothetical.

**Dry-run and idempotency as the operational mechanic for the confirmation
gate: `[unverified]`.** The general shape — a destructive tool exposing a
`dry_run` mode that previews its effect before a human confirms a real call,
paired with server-side idempotency so a retried call can't double-apply a
destructive change — is a natural extension of the MCP-primary annotation
material above and matches this repo's own existing snapshot→dry-run→apply
discipline, but no single fetched primary or secondary source in this
research pass documents the `dry_run` parameter convention or an audit-log
requirement explicitly enough to cite verbatim; the two paragraphs above (MCP
Blog's confirmation-step framing, and MCPSafe's annotation-mismatch
catalogue) are the actual sourced basis, and the `dry_run`-as-parameter-name
convention specifically should be treated as this repo's own existing
practice (see CLAUDE.md's `kf_plan_field_change`/`kf_apply_field_change`
pair, and the Implications section below) rather than an externally
documented standard.

**State management across calls is largely left to the server, not the
protocol.** Nothing in the MCP spec pages fetched for this research
prescribes a specific state-management pattern across multiple tool calls in
a build workflow — the spec provides the plumbing (structured
`inputSchema`/`outputSchema` per call, resource links a tool can hand back for
a later call to dereference) but the multi-step "plan → confirm → apply →
verify" discipline itself is a design choice the server author makes, not
something MCP hands you for free. `[unverified — no primary MCP source found
prescribing a specific cross-call state pattern beyond passing IDs/resource
links between calls; this is inference from the spec's absence of a stronger
mechanism, not a positive claim from a fetched source]`.

---

## Implications for kissflow-forge

**Bottom line on the pattern question: the literature favors the
per-field-primitive style over the compiled-plan style, for the natural-language
interaction model map #42 has already decided on — but with one important
correction to what "primitive" should mean.** None of the five sources above
argue for a privileged pipeline that pre-decides a plan before the agent gets
to compose anything; every one of them (areas 1, 2, 4, 5) assumes the calling
agent is the one doing the composition, and the server's job is to expose
safe, well-described, individually-composable operations plus the guardrails
(dry-run, annotations, validation) that make free composition safe. `forge_plan_app`
— which only accepts a whole `AppSpec` behind an HMAC-gated approval token and
then compiles the entire ordered `BuildPlan` in one call — is structurally the
opposite of that: it is the server pre-deciding the plan shape, with Claude
reduced to filling in an intake questionnaire beforehand. That is a legitimate
design for a *different* interaction model (a guided wizard), but it is not
what "general, validated, composable primitives" means, and it is not what
#42 decided.

**But "per-field-primitive" as currently implemented in `kf_*` is also not
simply the answer — it's the right granularity with two known gaps against
this literature.** `kf_plan_field_change` / `kf_apply_field_change` and
`kf_plan_step_visibility` / `kf_set_step_visibility` already implement the
single most emphasized pattern from area 5 (the plan/apply pair as MCP's
informal dry-run mechanic) and area 3 (the `kf_apply_field_change` docstring
already states its idempotency and conflict behavior in the description
itself — "a field whose name already exists is skipped, never duplicated.
Aborts with a conflict if the draft changed since it was read"). That is
exactly the actionable, self-describing contract area 1 and area 3 call for.
The `forge_*` per-capability tools (`forge_add_table`, `forge_build_workflow`,
`forge_set_visibility`, `forge_add_goto_gate`, `forge_set_branch_conditions`,
etc.) are the same granularity — one tool per natural task subdivision
(add a table, wire a workflow, set a branch condition) — which is precisely
the shape area 2 recommends: not one tool per raw API/graph-node operation,
and not one god-tool that swallows the whole build. That's the right
altitude to keep, generalized, once the compiled-plan gate is removed.

**Concrete changes implied by the research, mapped onto this repo's own tools:**

1. **Retire `forge_plan_app`'s privileged approval-token gate as the
   *entry point* to building; keep its underlying pieces as optional
   composable primitives.** `forge_intake_questions` (grilling), the design
   artifacts (`forge_render_flow_diagram`, `forge_render_mockups`,
   `forge_request_confirmation`), and `forge_approve_spec` are all still
   valuable — but the *literature's* dry-run/confirm pattern (area 5) wants
   confirmation scoped to each destructive *call*, not to one giant
   spec-shaped blob compiled once at the top. Claude, doing its own
   requirement analysis per map #42's decision, should be free to call
   `forge_render_mockups`/`forge_request_confirmation` on whatever slice of
   the build it's about to do next (one table, one workflow, one page), not
   only once at the very start of an entire app.

2. **Collapse the two parallel tool families instead of running them
   side-by-side.** Right now `kf_apply_field_change` and `forge_apply_fields`
   both exist and do overlapping work at different granularity — that is
   exactly the "ambiguous decision points" failure mode area 2 and area 4
   name directly (Anthropic, "Effective context engineering for AI agents").
   Pick the `kf_*` plan/apply granularity as the standard, port anything
   `forge_apply_fields`/`forge_apply_layout` do that `kf_apply_field_change`
   doesn't yet cover, and delete the duplicate rather than maintaining both —
   consistent with this repo's own subtraction-over-addition default.

3. **Every remaining `forge_*` write tool needs the same visible
   plan/apply (or `dry_run`) pair `kf_*` already has, not just a docstring
   warning.** `forge_build_workflow`, `forge_set_visibility`,
   `forge_add_table`, `forge_set_branch_conditions`, `forge_add_goto_gate`
   currently write directly; area 5's dry-run pattern and MCP's own
   `destructiveHint`/confirmation guidance both want a preview mode a caller
   can inspect before the real write, mirroring `kf_plan_field_change` →
   `kf_apply_field_change`. This *is* CLAUDE.md's own
   snapshot→dry-run→apply→read-back-verify→publish→audit discipline — the
   research doesn't ask this repo to adopt something new here, it confirms
   the discipline CLAUDE.md already mandates is the literature-endorsed shape,
   and flags where the tool surface hasn't caught up to it yet.

4. **Adopt MCP tool annotations (`destructiveHint`, `idempotentHint`,
   `readOnlyHint`) on every tool, not just prose in the docstring.**
   `kf_set_step_visibility`'s docstring already says "DESTRUCTIVE: every
   existing Permission on the flow is replaced" — that's exactly the
   information `destructiveHint: true` is designed to carry structurally, so
   a client can gate on it programmatically rather than only a human reading
   the docstring. This is cheap (a metadata field, not new logic) and gives
   any MCP client — not just a human reading source — the same warning.
   Combine with the area-5 caveat: annotations are hints a client *may*
   trust, not enforcement — this repo's own pre-destructive confirmation
   artifact requirement (a diagram or mockup for human sign-off) stays the
   real enforcement mechanism; annotations are the machine-readable label on
   top of it, not a replacement for it.

5. **Error messages should follow the same "unhelpful vs helpful" contrast
   Anthropic documents (area 3), and this repo already has the domain content
   to do it well.** CLAUDE.md's own catalogue of silent failure modes — a
   mis-cased Select literal that writes 200 and never fires, a stranded
   Appearance/Style chain, a misordered table host — are exactly the kind of
   failure a raw HTTP 200 or a generic exception would hide from the calling
   agent. Tool error responses (the `isError: true` path, per area 5's MCP
   spec reading) should say, concretely, which of these known traps was hit
   and what the correct next call looks like — not just "write failed" or a
   bare traceback. `forge_doctor`'s existing rule-naming behavior (e.g.
   flagging a dangling Step stamp by name) is already the right shape; extend
   that same specificity to every write tool's own error path, not only the
   read-only health check.

6. **Tool count and description-token cost should shape how many `forge_*`/
   `kf_*` tools survive the consolidation, not just which pattern wins.**
   With ~48 `@mcp.tool()` definitions already in `server.py`, this surface is
   large enough that area 2's concrete number (a 98.7% token-cost swing
   between flat-loaded and progressively-loaded tool definitions) is directly
   relevant, not theoretical. Two levers, in priority order: (a) consolidate
   before adding — collapsing the `kf_*`/`forge_*` duplication (point 2)
   directly shrinks the always-loaded tool list; (b) if the surface still
   grows past what fits comfortably in context after consolidation,
   Anthropic's own progressive-disclosure mechanisms — Skills (area 4) for
   the *procedural* domain knowledge (all of the CLAUDE.md build-order and
   gotcha content) and code-execution-style on-demand tool loading (area 2)
   for the tool *definitions* themselves — are the literature-endorsed way to
   keep a large, general primitive surface without paying its full token cost
   on every turn. Domain knowledge that is currently crammed into individual
   tool docstrings (e.g. `forge_plan_app`'s ~35-line docstring explaining the
   four ways the approval gate can be forged) is a good first candidate to
   move into a Skill or resource instead of paying its token cost on every
   tool-list load, per the mapping table in area 4.

7. **Where MCP resources fit that this repo doesn't yet use them:** the
   57 captured JSON node shapes in `shapes/`, the CONTEXT.md glossary, and
   the field-type/enum data currently served through tools like
   `kf_list_field_types` and `kf_get_flow_schema` are reference data, not
   procedures — area 4's mapping table puts that squarely in MCP **resources**
   (application/model-driven, fetched just-in-time) rather than tool
   descriptions or Skills. Exposing the shapes directory as MCP resources
   (rather than only as files on disk the agent has to already know to read)
   would let Claude pull a specific captured shape into context only when a
   build step actually needs it — directly the "just in time" pattern from
   area 4's context-engineering citation — instead of that knowledge living
   only in CLAUDE.md prose or being reconstructed by trial and error.

---

## Sources cited

**Anthropic-primary (5):**
1. Anthropic, "Writing effective tools for AI agents", Sept 11 2025 — https://www.anthropic.com/engineering/writing-tools-for-agents
2. Anthropic, "Building Effective Agents", Dec 19 2024 — https://www.anthropic.com/engineering/building-effective-agents
3. Anthropic, "Effective context engineering for AI agents", Sept 29 2025 — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
4. Anthropic, "Code execution with MCP: building more efficient AI agents", Nov 4 2025 — https://www.anthropic.com/engineering/code-execution-with-mcp
5. Claude/Anthropic, "Skills explained: How Skills compares to prompts, Projects, MCP, and subagents", March 5 2026 — https://claude.com/blog/skills-explained

**MCP project (official spec/blog, treated as primary per the source-priority instructions — 4):**
6. Model Context Protocol, "Tools" specification (2025-06-18 revision), fetched 2026-08-12 — https://modelcontextprotocol.io/specification/2025-06-18/server/tools
7. Model Context Protocol, "Resources" specification (2025-06-18 revision), fetched 2026-08-12 — https://modelcontextprotocol.io/specification/2025-06-18/server/resources
8. Model Context Protocol, "Prompts" specification (2025-06-18 revision), fetched 2026-08-12 — https://modelcontextprotocol.io/specification/2025-06-18/server/prompts
9. Model Context Protocol Blog, "Tool Annotations as Risk Vocabulary: What Hints Can and Can't Do", March 16 2026 — https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/

**Other (gap-fill, non-Anthropic — 1, independently fetched and verified):**
10. MCPSafe, "Destructive Tool Annotation Mismatch in MCP Servers" (threat catalogue entry MCP-200), © 2026, fetched 2026-08-12 — https://mcpsafe.io/threats/MCP-200

The `dry_run`-parameter convention and audit-logging requirement described in
area 5 are flagged inline as `[unverified]` — no fetched source in this pass
documents them explicitly; treat that specific detail as inference from the
sourced annotation/confirmation material, not as an independently cited claim.

Total distinct sources: **9 Anthropic/MCP-primary, 1 secondary (verified)** (10 total).
