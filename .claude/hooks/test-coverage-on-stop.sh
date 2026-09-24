#!/usr/bin/env bash
# Test coverage hook — runs when Claude finishes a turn (Stop hook).
#
# Goal: ensure tests pass and coverage ≥ 90%.
#   - If all good: exit 0, no output → Claude stays stopped, 0 tokens.
#   - If any issue: print actionable output to STDERR, exit 2 → Claude wakes up.
#   - Loop guard: max 2 attempts per session, then gives up silently.
#
# IMPORTANT: The message must go to STDERR, not stdout.
# Claude Code feeds stderr (not stdout) back to Claude on hook exit 2.
# If the message is on stdout, Claude sees nothing → no context → loop.
#
# Exit codes:
#   0 = all checks pass (or max attempts reached) — Claude stays stopped
#   2 = tests fail or coverage < 90% — Claude wakes up to fix

set -uo pipefail

counter_file="${CLAUDE_PROJECT_DIR}/.claude/hooks/.coverage-attempt-count"

# --- Loop guard -----------------------------------------------------------
attempts=0
if [ -f "$counter_file" ]; then
  attempts=$(cat "$counter_file" 2>/dev/null || echo 0)
fi

if [ "$attempts" -ge 2 ]; then
  rm -f "$counter_file"
  exit 0
fi

# --- Step 1: Run tests with coverage --------------------------------------
output=$(cd "${CLAUDE_PROJECT_DIR}" && uv run pytest --cov=src/app --cov-report=term-missing -q 2>&1)
rc=$?

# --- Step 2: If all checks pass, reset counter and exit silently ----------
if [ $rc -eq 0 ]; then
  rm -f "$counter_file"
  exit 0
fi

# --- Step 3: Tests failed or coverage < 90% — wake Claude -----------------
echo $((attempts + 1)) > "$counter_file"

# Extract uncovered files from the coverage report.
uncovered=$(echo "$output" | awk '/^src.*\.py/ && $3 > 0 {print "  " $1 " — " $3 " statements missed, lines: " $NF}')

# Redirect stdout to stderr so Claude Code feeds the message back to Claude.
exec 1>&2

echo "Test coverage is below 90%. You must write unit tests to fix this."
echo ""
if [ -n "$uncovered" ]; then
  echo "Uncovered files needing tests:"
  echo "$uncovered"
  echo ""
  echo "For each file above:"
  echo "  1. Read the source file to understand its functions"
  echo "  2. Write unit tests in tests/unit/ covering all functions and edge cases"
  echo "  3. Run: uv run pytest tests/unit/ --cov=src/app --cov-report=term-missing -q"
  echo ""
fi
echo "Full coverage report:"
echo "$output"
exit 2
