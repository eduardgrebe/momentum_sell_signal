#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run setup if uv is missing or the virtualenv hasn't been created yet
if ! command -v uv &>/dev/null || [ ! -d "$SCRIPT_DIR/.venv" ]; then
    bash "$SCRIPT_DIR/setup.sh"
    export PATH="$HOME/.local/bin:$PATH"
fi

# Hint about persistent monitoring when not already using --loop or --test-email
if [[ ! " $* " =~ " --loop " ]] && [[ ! " $* " =~ " --test-email " ]]; then
    trap 'echo ""; echo "Tip: run with --loop to keep monitoring, or bash install-service.sh to install as a persistent service."' EXIT
fi

exec uv run "$SCRIPT_DIR/sell_monitor.py" "$@"
