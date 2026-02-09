#!/usr/bin/env bash
# install.sh — Install Adam CPWplus driver on an Odoo IoT Box
#
# Run this ON the Pi (via terminal/SSH):
#
#   curl -fsSL https://raw.githubusercontent.com/thrivewell-partners/odoo-cpwplus-driver/main/install.sh | sudo bash
#
# What it does:
#   1. Downloads AdamCPWplusDriver.py from GitHub
#   2. Copies to the persistent location (survives reboots)
#   3. Copies to the active location (works immediately)
#   4. Restarts the Odoo service
#
# To uninstall:
#   curl -fsSL https://raw.githubusercontent.com/thrivewell-partners/odoo-cpwplus-driver/main/install.sh | sudo bash -s -- --uninstall

set -euo pipefail

# --- Configuration ---
REPO_BASE="https://raw.githubusercontent.com/thrivewell-partners/odoo-cpwplus-driver/main"
DRIVER_FILE="AdamCPWplusDriver.py"
PERSISTENT_DIR="/root_bypass_ramdisks/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"
ACTIVE_DIR="/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"

# Colors (if terminal supports them)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# --- Uninstall ---
if [[ "${1:-}" == "--uninstall" ]]; then
    echo ""
    echo "=== Uninstalling Adam CPWplus Driver ==="
    echo ""

    for dir in "$PERSISTENT_DIR" "$ACTIVE_DIR"; do
        if [[ -f "${dir}/${DRIVER_FILE}" ]]; then
            rm -f "${dir}/${DRIVER_FILE}"
            info "Removed ${dir}/${DRIVER_FILE}"
        else
            warn "Not found: ${dir}/${DRIVER_FILE} (already removed?)"
        fi
    done

    info "Restarting Odoo service..."
    systemctl restart odoo 2>/dev/null || service odoo restart 2>/dev/null || warn "Could not restart Odoo — restart manually"

    echo ""
    info "Uninstall complete. The CPWplus driver has been removed."
    exit 0
fi

# --- Install ---
echo ""
echo "==========================================="
echo "  Adam CPWplus Driver — IoT Box Installer"
echo "==========================================="
echo ""

# Check we're running as root (needed for filesystem writes)
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
    echo "  Try: curl -fsSL ${REPO_BASE}/install.sh | sudo bash"
    exit 1
fi

# Check we're on an IoT Box (look for Odoo service or directory)
if [[ ! -d "/home/pi/odoo" ]] && [[ ! -d "/root_bypass_ramdisks/home/pi/odoo" ]]; then
    error "This doesn't look like an Odoo IoT Box"
    echo "  Expected /home/pi/odoo to exist"
    exit 1
fi

# Step 1: Remount filesystems as writable
info "Remounting filesystems as writable..."
mount -o remount,rw / 2>/dev/null || true
mount -o remount,rw /root_bypass_ramdisks 2>/dev/null || true

# Step 2: Download the driver
info "Downloading ${DRIVER_FILE} from GitHub..."
TMPFILE=$(mktemp /tmp/cpwplus-XXXXXX.py)
if ! curl -fsSL "${REPO_BASE}/${DRIVER_FILE}" -o "$TMPFILE"; then
    error "Failed to download driver from GitHub"
    echo "  URL: ${REPO_BASE}/${DRIVER_FILE}"
    echo "  Check your internet connection and try again"
    rm -f "$TMPFILE"
    exit 1
fi

# Verify we got a Python file (not an HTML error page)
if ! head -1 "$TMPFILE" | grep -q "coding: utf-8\|^#\|^import"; then
    error "Downloaded file doesn't look like a Python driver"
    echo "  This may mean the GitHub URL is wrong or the repo is not public"
    rm -f "$TMPFILE"
    exit 1
fi

info "Download complete ($(wc -c < "$TMPFILE") bytes)"

# Step 3: Copy to persistent location
info "Installing to persistent location..."
mkdir -p "$PERSISTENT_DIR"
cp "$TMPFILE" "${PERSISTENT_DIR}/${DRIVER_FILE}"
chmod 644 "${PERSISTENT_DIR}/${DRIVER_FILE}"
echo "  -> ${PERSISTENT_DIR}/${DRIVER_FILE}"

# Step 4: Copy to active location
info "Installing to active location..."
mkdir -p "$ACTIVE_DIR"
cp "$TMPFILE" "${ACTIVE_DIR}/${DRIVER_FILE}"
chmod 644 "${ACTIVE_DIR}/${DRIVER_FILE}"
echo "  -> ${ACTIVE_DIR}/${DRIVER_FILE}"

# Cleanup temp file
rm -f "$TMPFILE"

# Step 5: Restart Odoo
info "Restarting Odoo service..."
if systemctl restart odoo 2>/dev/null; then
    info "Odoo restarted successfully"
elif service odoo restart 2>/dev/null; then
    info "Odoo restarted successfully"
else
    warn "Could not restart Odoo automatically"
    echo "  Try manually: sudo systemctl restart odoo"
fi

echo ""
echo "==========================================="
echo "  Installation complete!"
echo "==========================================="
echo ""
echo "  Next steps:"
echo "    1. Connect the CPWplus via USB-to-Serial adapter"
echo "    2. The scale should appear on the IoT Box homepage"
echo "    3. In Odoo POS settings, select it as the Electronic Scale"
echo ""
echo "  IMPORTANT: Disable 'Automatic drivers update' in Odoo"
echo "    (IoT app -> IoT Box -> Settings)"
echo "    Otherwise this driver may be overwritten on reboot."
echo ""
echo "  To uninstall:"
echo "    curl -fsSL ${REPO_BASE}/install.sh | sudo bash -s -- --uninstall"
echo ""
