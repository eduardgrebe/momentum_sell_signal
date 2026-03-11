#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Eduard Grebe Consulting (Pty) Ltd.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run setup if uv is missing or the virtualenv hasn't been created yet
if ! command -v uv &>/dev/null || [ ! -d "$SCRIPT_DIR/.venv" ]; then
    bash "$SCRIPT_DIR/setup.sh"
    export PATH="$HOME/.local/bin:$PATH"
fi

exec uv run "$SCRIPT_DIR/sell_monitor.py" "$@"
