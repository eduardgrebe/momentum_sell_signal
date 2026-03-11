#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Eduard Grebe <eduard@grebe.consulting>
set -euo pipefail

cd "$(dirname "$0")"

# Install uv in userspace if not already available
if ! command -v uv &>/dev/null; then
    echo "uv not found — installing to ~/.local/bin ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add to PATH for the rest of this script
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "$(uv --version)"

# Sync dependencies declared in pyproject.toml
uv sync

echo ""
echo "Setup complete. Run the monitor with:"
echo "  uv run sell_monitor.py"
echo "  uv run sell_monitor.py --loop"
echo "  uv run sell_monitor.py --coin bitcoin --days 14"
