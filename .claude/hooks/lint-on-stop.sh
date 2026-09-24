#!/usr/bin/env bash
# Lint hook — runs when Claude finishes a turn (Stop hook).
#
# Goal: catch lint errors without wasting tokens on success.
#   - If lint passes: exit 0, no output → Claude stays stopped, 0 tokens.
#   - If lint fails: auto-fix with `make format`, re-lint.
#     - If still failing: print errors to STDERR, exit 2 → Claude wakes up.
#     - If fixed: exit 0, no output → 0 tokens.
#   - Loop guard: max 2 attempts per session, then gives up silently.
#
# IMPORTANT: The message must go to STDERR, not stdout.
# Claude Code feeds stderr (not stdout) back to Claude on hook exit 2.
#
# Exit codes:
#   0 = lint passes (or was auto-fixed, or max attempts reached) — Claude stays stopped
#   2 = lint still fails after auto-fix — Claude wakes up with error output

set -uo pipefail

counter_file="${CLAUDE_PROJECT_DIR}/.claude/hooks/.lint-attempt-count"

# --- Loop guard -----------------------------------------------------------
attempts=0
if [ -f "$counter_file" ]; then
  attempts=$(cat "$counter_file" 2>/dev/null || echo 0)
fi

if [ "$attempts" -ge 2 ]; then
  rm -f "$counter_file"
  exit 0
fi

# Step 1: Run lint and capture all output (stdout + stderr).
output=$(cd "${CLAUDE_PROJECT_DIR}" && make lint 2>&1)
rc=$?

# Step 2: If lint passed, we're done — reset counter and exit 0.
if [ $rc -eq 0 ]; then
  rm -f "$counter_file"
  exit 0
fi

# Step 3: Lint failed — try to auto-fix with `make format`.
(cd "${CLAUDE_PROJECT_DIR}" && make format) >/dev/null 2>&1

# Step 4: Re-run lint after auto-fix.
output=$(cd "${CLAUDE_PROJECT_DIR}" && make lint 2>&1)
rc=$?

# Step 5: If lint still fails after auto-fix, wake Claude with the errors.
if [ $rc -ne 0 ]; then
  echo $((attempts + 1)) > "$counter_file"
  # Redirect stdout to stderr so Claude Code feeds the message back to Claude.
  exec 1>&2
  echo "$output"
  exit 2
fi

# Step 6: Auto-fix resolved all issues — reset counter and exit 0.
rm -f "$counter_file"
exit 0
