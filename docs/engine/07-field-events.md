## Field events

⚠️ A CORRECTED BELIEF (2026-08-12, #48 browser capture): this section used to
open "Kissflow has no formula or computed field type" — WRONG on the current
platform. The field Settings tab carries an "Is this a computed field?"
toggle opening a full Formula builder; saving writes a FOURTH Expression
owner, the Field itself (`Field::Expression` → Expression{Field, ExpressionStr,
Expression::Node} — same Node AST family as branch conditions, field refs BY
ID, toggle disables DefaultValue). See docs/capabilities/config.computed.md +
shapes/field_computed_expression.json. Runtime caveat: the formula did NOT
evaluate on an admin data-plane fill — evaluation is client/submit-side,
runtime proof still open. Field events below remain a real, separate
mechanism for script-based computation: a script the client SDK runs in
response to a field change.

```
Field { ..., "Field::Event": ["Event_Sample01"] }        # back-reference, bidirectional
Event { Id, Kind:"Event", Field:<field id>, Trigger:"onChange", Script:"<raw JS>" }
```

**The trigger is a FUNCTION of the SOURCE field's type**, and all three wire
strings are now LIVE-OBSERVED on a published flow (2026-08-10 eval-case read,
issue #12 — replacing the earlier belief that only `onChange` was captured):
a Select source fires `onClick`, Date and Number sources fire `onSelect`,
Text/Textarea sources fire `onChange`. A hand-picked wrong trigger writes
fine, publishes fine, and simply never fires — derive it from the source
type (`kfforge.intake.schema.trigger_for`), never guess it. User→`onSelect`
and Boolean→`onClick` are family-inferred, still unverified live.

Six field types never get an event at all — the builder offers no Event tab
for any of them, so there's no trigger string to find no matter how hard you
look: **Attachment, Image, Rich text, Signature, Sequence number,
Geolocation.**

Two rules the event editor enforces, both learned by having a paste rejected:

- The event box is parsed as a **plain function body**, not a module — a
  top-level `await` is a `SyntaxError` in that context. Wrap everything in an
  immediately-invoked async function: `(async () => { ... })();`
- **`kf` is already injected into the event's scope. `KFSDK` is undefined
  here** — calling `KFSDK.initialize()` fails immediately. (`KFSDK.initialize()`
  is for a different host entirely — custom components — not a field event.)

**Always attach the event to the SOURCE field, never to the computed target
field.** An event on the target field only fires when a human edits that
field directly, which never happens for a value that's supposed to be
computed. The SDK available inside an event is read-and-update only — it can
read fields and write field values, but it cannot create or delete fields,
rows, or tables. It fills things in; it doesn't build structure.
