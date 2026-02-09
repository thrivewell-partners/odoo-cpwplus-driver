# Adam CPWplus Scale Driver for Odoo POS

Custom IoT Box driver connecting Adam Equipment CPWplus floor scales to Odoo Point of Sale via RS-232.

## Why a Custom Driver?

Odoo ships with an `AdamEquipmentDriver` built for the **AZExtra** series. The CPWplus has different protocol requirements:

| Parameter | Built-in AZExtra | CPWplus (this driver) |
|-----------|-------------------|----------------------|
| Baud rate | 4800 | 9600 |
| Weight regex | `\s*([0-9.]+)kg` | `[GN]/W\s*[+-]\s*([0-9.]+)\s*(?:lb\|kg\|oz)` |
| Units | kg only | lb, kg, oz |
| Polling delay | 5s (AZExtra beeps) | 0.5s |
| Device probing | No identification | Probes with `G` command, checks for `G/W` |
| Tare/Zero | Not wired | `T` and `Z` commands |

## Hardware Requirements

- **Adam CPWplus scale** (any capacity: 35lb, 75lb, 150lb, etc.)
- **Raspberry Pi IoT Box** with Odoo IoT subscription
- **Null modem RS-232 cable** — Adam part `3074010266` (DB9F-to-DB9F crossover)
- **USB-to-Serial adapter** — FTDI or Prolific chipset recommended

**Connection chain:**
```
CPWplus DB9 → Null Modem Cable → USB-to-Serial Adapter → Pi USB Port
```

## Scale Configuration

Before connecting to the IoT Box, configure the CPWplus via its setup menu:

1. Press and hold **SETUP** until the display shows the first setting
2. Navigate to **baud rate** → set to `b 9600`
3. Navigate to **parity** → set to `nonE` (None)
4. Navigate to **transmission mode** → set to `trn 1` (demand mode)
5. Navigate to **units** → set to desired unit (`lb` for Henderson)
6. Press **SETUP** to exit and save

> **Important:** `trn 1` (demand mode) means the scale only sends weight when asked via the `G` command. Do NOT use `trn 2` (continuous/streaming mode) — the driver expects demand/response behavior.

## Installation

### One-Line Install (on the IoT Box)

Open a terminal on the Pi (via Odoo IoT Box remote access or physical keyboard) and run:

```bash
curl -fsSL https://raw.githubusercontent.com/thrivewell-partners/odoo-cpwplus-driver/main/install.sh | sudo bash
```

That's it. The script downloads the driver, installs it to both persistent and active locations, and restarts Odoo.

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/thrivewell-partners/odoo-cpwplus-driver/main/install.sh | sudo bash -s -- --uninstall
```

### Pre-Install Test (Optional)

Connect the CPWplus to any Linux/Mac machine with the USB-to-Serial adapter to verify communication before touching the IoT Box:

```bash
pip install pyserial
python3 test_serial.py /dev/ttyUSB0
```

### Prevent Auto-Update Overwrite

The IoT Box downloads handlers from the Odoo server on every boot. Since Henderson runs Odoo Online (SaaS), the server won't include this custom driver and it could be overwritten.

**Fix:** Disable automatic driver updates in Odoo:
1. Go to **IoT app** → select the IoT Box
2. Uncheck **"Automatic drivers update"**
3. Save

## POS Configuration

1. Go to **POS → Configuration → Settings**
2. Enable **IoT Box** under Connected Devices
3. Select the IoT Box from the dropdown
4. Under **Electronic Scale**, select **"Adam CPWplus Serial Scale"**
5. Save and reload the POS

## Verification

### Check IoT Box Homepage

Open `http://<iot_box_ip>:8069` — the CPWplus should appear in the device list.

### Check Logs

```bash
ssh pi@192.168.1.50 'sudo journalctl -u odoo -f'
```

Look for:
- `Probing /dev/ttyUSB0 with protocol Adam CPWplus` — driver is testing the port
- `CPWplus identified on /dev/ttyUSB0` — device recognized
- `Adam Cpwplus Serial Scale` — device name registered

### Test in POS

1. Open a POS session
2. Select a product sold by weight
3. The scale screen should appear with live weight readings
4. Place items on the scale — weight should update every 0.5s

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Scale not detected | Wrong baud rate | Check scale is set to `b 9600` |
| Scale not detected | No null modem cable | Must use crossover cable (TX/RX swapped) |
| Scale not detected | USB adapter not recognized | Check `dmesg \| tail` on Pi for USB detection |
| Weight shows 0 | Scale in `trn 2` mode | Set to `trn 1` (demand mode) |
| Weight shows 0 | Wrong units configured | Verify regex matches your unit (lb/kg/oz) |
| AZExtra driver claims port | Priority issue | Our driver has priority=10 > AZExtra's priority=0 |
| Driver disappears after reboot | Auto-update overwrites it | Disable automatic driver updates in IoT settings |
| Permission denied on deploy | Pi filesystem is read-only | Run `mount -o remount,rw /` first |
| "No weight match" in logs | Response format mismatch | Run `test_serial.py` to see raw responses |

## Files

| File | Purpose |
|------|---------|
| `AdamCPWplusDriver.py` | The IoT Box driver (deployed to the Pi) |
| `install.sh` | One-line installer — run on the Pi via `curl \| sudo bash` |
| `deploy.sh` | Alternative: SSH-based deployment from your workstation |
| `test_serial.py` | Pre-deployment serial communication test |
| `README.md` | This file |
