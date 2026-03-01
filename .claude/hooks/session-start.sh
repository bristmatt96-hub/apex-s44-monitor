#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

echo "Installing Python dependencies..."
pip install --quiet --no-warn-script-location \
  -r requirements.txt 2>/dev/null || true

# Install linter (ruff is fast and minimal config needed)
pip install --quiet --no-warn-script-location ruff 2>/dev/null || true

# Set PYTHONPATH so module imports resolve from project root
echo 'export PYTHONPATH="$CLAUDE_PROJECT_DIR"' >> "$CLAUDE_ENV_FILE"

echo "Session start hook complete."
