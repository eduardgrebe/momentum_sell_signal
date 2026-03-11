#!/usr/bin/env bash
# Install sell-monitor as a persistent background service.
#
# macOS  → LaunchAgent  (~/.config/systemd/user/ not applicable)
# Linux  → systemd user service
#
# Any arguments passed to this script are forwarded to sell_monitor.py,
# e.g.:  bash install-service.sh --coin bitcoin --interval 1800
#
# To uninstall:
#   macOS:  launchctl unload ~/Library/LaunchAgents/com.sell-monitor.plist
#           rm ~/Library/LaunchAgents/com.sell-monitor.plist
#   Linux:  systemctl --user disable --now sell-monitor
#           rm ~/.config/systemd/user/sell-monitor.service

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_SCRIPT="$SCRIPT_DIR/sell_monitor.py"

# ── Locate uv ────────────────────────────────────────────────────────────────
UV="$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")"
if [ ! -x "$UV" ]; then
    echo "Error: uv not found. Run setup.sh first." >&2
    exit 1
fi

# ── Build the command (always includes --loop; caller adds extras) ────────────
MONITOR_ARGS=("--loop" "$@")

# ── Detect OS ────────────────────────────────────────────────────────────────
case "$(uname -s)" in
    Darwin) OS=macos ;;
    Linux)  OS=linux ;;
    *)
        echo "Error: unsupported OS '$(uname -s)'. Only macOS and Linux are supported." >&2
        exit 1
        ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
# macOS — LaunchAgent
# ─────────────────────────────────────────────────────────────────────────────
install_macos() {
    local plist="$HOME/Library/LaunchAgents/com.sell-monitor.plist"
    local logdir="$HOME/Library/Logs"
    local label="com.sell-monitor"

    mkdir -p "$HOME/Library/LaunchAgents"

    # Build <array> of ProgramArguments
    local args_xml=""
    args_xml+="        <string>$UV</string>"$'\n'
    args_xml+="        <string>run</string>"$'\n'
    args_xml+="        <string>$MONITOR_SCRIPT</string>"$'\n'
    for arg in "${MONITOR_ARGS[@]}"; do
        args_xml+="        <string>$arg</string>"$'\n'
    done

    cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$label</string>
    <key>ProgramArguments</key>
    <array>
$args_xml    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$logdir/sell-monitor.log</string>
    <key>StandardErrorPath</key>
    <string>$logdir/sell-monitor.error.log</string>
</dict>
</plist>
EOF

    # Unload first if already loaded (update case)
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"

    echo "LaunchAgent installed and started."
    echo "  Plist:  $plist"
    echo "  Stdout: $logdir/sell-monitor.log"
    echo "  Stderr: $logdir/sell-monitor.error.log"
    echo ""
    echo "To uninstall:"
    echo "  launchctl unload $plist"
    echo "  rm $plist"
}

# ─────────────────────────────────────────────────────────────────────────────
# Linux — systemd user service
# ─────────────────────────────────────────────────────────────────────────────
install_linux() {
    local service_dir="$HOME/.config/systemd/user"
    local service_file="$service_dir/sell-monitor.service"

    mkdir -p "$service_dir"

    # Build ExecStart line
    local exec_start="$UV run $MONITOR_SCRIPT"
    for arg in "${MONITOR_ARGS[@]}"; do
        exec_start+=" $arg"
    done

    cat > "$service_file" <<EOF
[Unit]
Description=Sell Monitor — momentum-based crypto sell signal monitor
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$exec_start
WorkingDirectory=$SCRIPT_DIR
Restart=on-failure
RestartSec=60

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now sell-monitor

    echo "systemd user service installed and started."
    echo "  Service file: $service_file"
    echo "  Logs:         journalctl --user -u sell-monitor -f"
    echo ""

    # Check if linger is enabled (required for service to survive logout/reboot)
    if ! loginctl show-user "$(whoami)" --property=Linger | grep -q "Linger=yes"; then
        echo "Note: to keep the service running after logout and across reboots, run:"
        echo "  loginctl enable-linger $(whoami)"
    fi

    echo ""
    echo "To uninstall:"
    echo "  systemctl --user disable --now sell-monitor"
    echo "  rm $service_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
echo "Installing sell-monitor as a persistent service on $OS..."
echo "Command: $UV run $MONITOR_SCRIPT ${MONITOR_ARGS[*]}"
echo ""
read -r -p "Proceed? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

case "$OS" in
    macos) install_macos ;;
    linux) install_linux ;;
esac
