## Expressions

An `Expression` node is not always a branch condition — its owner key tells
you what it actually is, and **the owner key is one of three**, each meaning
something different:

| Owner key    | Meaning                                    |
|--------------|---------------------------------------------|
| `ProcessDef` | a branch condition (which path an item takes) |
| `Activity`   | a `GotoTask` loop condition (see Workflow)     |
| `Property`   | a value-generator prefix (e.g. an auto-number scheme) |
| `Field`      | a computed-field formula (#48, 2026-08-12 — see Field events) |

Always branch on which key is present before treating an `Expression` as
routing logic — treating a `Property`-owned Expression as a branch condition
misreads a formatting rule as broken routing.

The full node shape is a small AST, not a flat value:

```
owner --Expression--> Expression{ExpressionStr, Expression::Node:[root]}
root Node{Type:"Function", Value:"=", Syntax:"Infix", Node::Node:[lhs, rhs],
          DataType:"Boolean", FieldRefCount:<n>}
  lhs Node{Type:"Field",  Field:<field id>, DataType:"String", Node:<parent>}
  rhs Node{Type:"Static", Value:"Option A", DataType:"String", Node:<parent>}
Field{..., "Field::Node":[every node that references this field]}   # bidirectional, must be maintained
```

- **`ExpressionStr` is only a readable mirror** of the AST (and it references
  fields by id, not by name) — it is not itself evaluated. Build the `Node`
  tree; do not stop at writing the string.
- **A Boolean literal is a zero-arg `Function` node, not a `Static`.** A
  literal `false` is:

```json
{"Type":"Function","Value":"false","DataType":"Boolean","Category":"Boolean","Node":"<parent>"}
```

  No `Node::Node`, no `Syntax` key. A `Static` node with the string `"false"`
  is a different type entirely and will never match a Boolean comparison.
- **`Category` on the root node is the class of the operands being compared,
  not the result type.** Every root is shaped
  `{Type:"Function", Value:"=", Syntax:"Infix", DataType:"Boolean", FieldRefCount:<n>}`
  — `DataType` is always `"Boolean"` because `=` always produces a boolean —
  but `Category` is `"String"` when comparing two strings/Selects and
  `"Boolean"` when comparing two Booleans. Set `Category` from what the
  operands are, never copy it from `DataType`.
- **Literals are case-sensitive and never validated by the write API.** A
  typo'd option value (wrong case, extra space, anything not byte-identical to
  the real option) writes fine, publishes fine, and simply never fires — the
  branch or gate silently goes the other way forever. **Never guess a
  literal — read it.** Fetch the live list of valid option values for that
  field before writing any literal into an Expression, and compare
  byte-for-byte.
- **Rewiring a condition to point at a different field is six edits, not
  one:**
  1. the Field node's `Field` reference,
  2. that node's `DataType`,
  3. the literal node (value and, if the type changed, its shape),
  4. the root's `Category`,
  5. the `ExpressionStr` mirror,
  6. moving the `Field::Node` back-reference off the old field and onto the new one.

  Miss any one of the six and you get a graph that looks right on casual read
  but silently evaluates against stale data.
