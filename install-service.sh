#!/usr/bin/env bash
# Install sell-monitor as a persistent background service.
#
# macOS  → LaunchAgent  (~/Library/LaunchAgents/)
# Linux  → systemd user service (~/.config/systemd/user/)
#
# Any arguments passed to this script are forwarded to sell_monitor.py,
# e.g.:  bash install-service.sh --coin bitcoin --interval 1800
#
# Multiple assets are supported — each gets its own named service:
#   bash install-service.sh --coin bitcoin
#   bash install-service.sh --coin staked-ether
#
# To uninstall (macOS):
#   launchctl unload ~/Library/LaunchAgents/com.sell-monitor.<coin>.plist
#   rm ~/Library/LaunchAgents/com.sell-monitor.<coin>.plist
#
# To uninstall (Linux):
#   systemctl --user disable --now sell-monitor-<coin>
#   rm ~/.config/systemd/user/sell-monitor-<coin>.service

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

# ── Derive service identifier from --coin (default: staked-ether) ────────────
COIN_ID="staked-ether"
args=("$@")
for (( i=0; i<${#args[@]}; i++ )); do
    if [[ "${args[$i]}" == "--coin" && $((i+1)) -lt ${#args[@]} ]]; then
        COIN_ID="${args[$((i+1))]}"
    fi
done
SERVICE_SUFFIX="$COIN_ID"

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
    local label="com.sell-monitor.$SERVICE_SUFFIX"
    local plist="$HOME/Library/LaunchAgents/${label}.plist"
    local logdir="$HOME/Library/Logs"

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
    <string>$logdir/sell-monitor-${SERVICE_SUFFIX}.log</string>
    <key>StandardErrorPath</key>
    <string>$logdir/sell-monitor-${SERVICE_SUFFIX}.error.log</string>
</dict>
</plist>
EOF

    # Unload first if already loaded (update case)
    launchctl unload "$plist" 2>/dev/null || true
    launchctl load -w "$plist"

    echo "LaunchAgent installed and started."
    echo "  Label:  $label"
    echo "  Plist:  $plist"
    echo "  Stdout: $logdir/sell-monitor-${SERVICE_SUFFIX}.log"
    echo "  Stderr: $logdir/sell-monitor-${SERVICE_SUFFIX}.error.log"
    echo ""
    echo "To uninstall:"
    echo "  launchctl unload $plist"
    echo "  rm $plist"
}

# ─────────────────────────────────────────────────────────────────────────────
# Linux — systemd user service
# ─────────────────────────────────────────────────────────────────────────────
install_linux() {
    local service_name="sell-monitor-${SERVICE_SUFFIX}"
    local service_dir="$HOME/.config/systemd/user"
    local service_file="$service_dir/${service_name}.service"

    mkdir -p "$service_dir"

    # Build ExecStart line
    local exec_start="$UV run $MONITOR_SCRIPT"
    for arg in "${MONITOR_ARGS[@]}"; do
        exec_start+=" $arg"
    done

    cat > "$service_file" <<EOF
[Unit]
Description=Sell Monitor ($COIN_ID) — momentum-based crypto sell signal monitor
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
    systemctl --user enable --now "$service_name"

    echo "systemd user service installed and started."
    echo "  Service: $service_name"
    echo "  File:    $service_file"
    echo "  Logs:    journalctl --user -u $service_name -f"
    echo ""

    # Check if linger is enabled (required for service to survive logout/reboot)
    if ! loginctl show-user "$(whoami)" --property=Linger 2>/dev/null | grep -q "Linger=yes"; then
        echo "Note: to keep the service running after logout and across reboots, run:"
        echo "  loginctl enable-linger $(whoami)"
    fi

    echo ""
    echo "To uninstall:"
    echo "  systemctl --user disable --now $service_name"
    echo "  rm $service_file"
}

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
echo "Installing sell-monitor for '$COIN_ID' as a persistent service on $OS..."
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
