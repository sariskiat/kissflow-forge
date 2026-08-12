---
id: field.rich-text
name: Rich text field
status: inferred
modules:
  process: unknown
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Rich text"
shapes: []
params: []
---

## What

A formatted-text field (bold, lists, links). Shape **not captured live**:
copilot repeatedly reported *"successfully added the Rich text field"* while the
node was ABSENT from every flow's read-back — a textbook fake-success (THE RULE:
the reply lied, the graph had nothing). The likely real shape, per CLAUDE.md, is
a `Textarea` node with `AllowFormatting:true` — but that is inferred, not
captured here.

## Where

Form builder field palette ("Rich text"). Because copilot fakes it, the capture
path is the **builder UI** (build one by hand, read back), or the existing
Textarea shape with `AllowFormatting`.

## Best practice

- Never trust a copilot "Rich text added" reply — read back the graph; the node
  is usually absent.
- If a build needs rich text, capture the real `Textarea + AllowFormatting`
  shape off a builder-authored example first.
- Rich text is one of the six event-less types — it cannot be a computed source.

## Validation

Unknown until captured (config-tabs sweep #48 + a builder capture owe this).

## Computed

One of the six event-less types (no Event tab) — cannot be a computed source.
Can be a computed target once the shape is known.
