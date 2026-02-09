#!/usr/bin/env bash
# deploy.sh — Deploy AdamCPWplusDriver.py to an Odoo IoT Box via SSH
#
# Usage:
#   ./deploy.sh <iot_box_ip> [ssh_user] [ssh_password]
#
# Examples:
#   ./deploy.sh 192.168.1.50
#   ./deploy.sh 192.168.1.50 pi raspberry
#
# The script will:
#   1. Copy the driver to the persistent location (/root_bypass_ramdisks/...)
#   2. Copy to the active location (/home/pi/odoo/addons/...)
#   3. Restart the Odoo service so the driver loads
#
# Prerequisites:
#   - sshpass (install with: sudo apt install sshpass)
#   - The IoT Box must be reachable on the network
#   - Default credentials: pi / raspberry

set -euo pipefail

DRIVER_FILE="AdamCPWplusDriver.py"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER_PATH="${SCRIPT_DIR}/${DRIVER_FILE}"

# IoT Box paths
PERSISTENT_DIR="/root_bypass_ramdisks/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"
ACTIVE_DIR="/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"

# --- Parse arguments ---
IOT_IP="${1:-}"
SSH_USER="${2:-pi}"
SSH_PASS="${3:-raspberry}"

if [[ -z "$IOT_IP" ]]; then
    echo "Usage: $0 <iot_box_ip> [ssh_user] [ssh_password]"
    echo ""
    echo "Example: $0 192.168.1.50"
    exit 1
fi

if [[ ! -f "$DRIVER_PATH" ]]; then
    echo "ERROR: Driver file not found at: $DRIVER_PATH"
    exit 1
fi

echo "=== Deploying ${DRIVER_FILE} to IoT Box at ${IOT_IP} ==="
echo ""

# Check if sshpass is available (for non-interactive password auth)
USE_SSHPASS=false
if command -v sshpass &>/dev/null; then
    USE_SSHPASS=true
fi

# Build SSH/SCP commands
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"
if [[ "$USE_SSHPASS" == true ]]; then
    SSH_CMD="sshpass -p '${SSH_PASS}' ssh ${SSH_OPTS} ${SSH_USER}@${IOT_IP}"
    SCP_CMD="sshpass -p '${SSH_PASS}' scp ${SSH_OPTS}"
else
    echo "Note: sshpass not found — you'll be prompted for the password."
    echo "      Install sshpass for non-interactive deployment: sudo apt install sshpass"
    echo ""
    SSH_CMD="ssh ${SSH_OPTS} ${SSH_USER}@${IOT_IP}"
    SCP_CMD="scp ${SSH_OPTS}"
fi

# Step 1: Remount filesystems as writable
echo "[1/4] Remounting filesystems as writable..."
eval "${SSH_CMD}" "sudo mount -o remount,rw / 2>/dev/null; sudo mount -o remount,rw /root_bypass_ramdisks 2>/dev/null; echo 'Filesystems remounted'"

# Step 2: Copy to persistent location (survives reboots)
echo "[2/4] Copying driver to persistent location..."
eval "${SCP_CMD}" "${DRIVER_PATH}" "${SSH_USER}@${IOT_IP}:/tmp/${DRIVER_FILE}"
eval "${SSH_CMD}" "sudo mkdir -p ${PERSISTENT_DIR} && sudo cp /tmp/${DRIVER_FILE} ${PERSISTENT_DIR}/${DRIVER_FILE}"
echo "  -> ${PERSISTENT_DIR}/${DRIVER_FILE}"

# Step 3: Copy to active location (immediate use)
echo "[3/4] Copying driver to active location..."
eval "${SSH_CMD}" "sudo mkdir -p ${ACTIVE_DIR} && sudo cp /tmp/${DRIVER_FILE} ${ACTIVE_DIR}/${DRIVER_FILE}"
echo "  -> ${ACTIVE_DIR}/${DRIVER_FILE}"

# Step 4: Restart Odoo service
echo "[4/4] Restarting Odoo service..."
eval "${SSH_CMD}" "sudo systemctl restart odoo 2>/dev/null || sudo service odoo restart 2>/dev/null || echo 'Warning: Could not restart odoo service automatically'"

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Next steps:"
echo "  1. Open http://${IOT_IP}:8069 — the CPWplus should appear in the device list"
echo "  2. In Odoo POS settings, select the IoT Box and choose the CPWplus as the scale"
echo "  3. Check logs if needed:  ssh ${SSH_USER}@${IOT_IP} 'sudo journalctl -u odoo -f'"
echo ""
echo "IMPORTANT: Disable 'Automatic drivers update' in IoT Box settings to prevent"
echo "  the driver from being overwritten on reboot. (IoT app -> IoT Box -> Settings)"
