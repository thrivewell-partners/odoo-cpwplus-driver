# CPWplus Driver - Odoo 19 Migration Changes

Date: 2026-02-09

## Summary

Three issues prevented the driver from working on Odoo 19 IoT Boxes:

1. **Module path rename** — Odoo 19 renamed `hw_drivers` to `iot_drivers` and switched to snake_case filenames
2. **FTDI DTR/RTS flow control** — pyserial's default line states prevent the CPWplus from responding on Raspberry Pi FTDI adapters
3. **Data key rename** — Odoo 19's ScaleDriver expects `self.data['result']` instead of `self.data['value']`

---

## Change 1: Fix Python imports in `AdamCPWplusDriver.py`

**Lines 29-33**

```python
# OLD (broken on Odoo 19):
from odoo.addons.hw_drivers.iot_handlers.drivers.SerialBaseDriver import (
    SerialProtocol,
    serial_connection,
)
from odoo.addons.hw_drivers.iot_handlers.drivers.SerialScaleDriver import ScaleDriver

# NEW (Odoo 19):
from odoo.addons.iot_drivers.iot_handlers.drivers.serial_base_driver import (
    SerialProtocol,
    serial_connection,
)
from odoo.addons.iot_drivers.iot_handlers.drivers.serial_scale_driver import ScaleDriver
```

**Why:** Odoo 19 renamed the `hw_drivers` addon to `iot_drivers` and changed filenames from PascalCase to snake_case. The class names (`SerialProtocol`, `serial_connection`, `ScaleDriver`) stayed the same.

**Error before fix:**
```
ModuleNotFoundError: No module named 'odoo.addons.hw_drivers.iot_handlers.drivers.SerialBaseDriver'
```

---

## Change 2: Add DTR/RTS flow control fix in `AdamCPWplusDriver.py`

**New static method added to the class (after `priority = 10`):**

```python
@staticmethod
def _disable_flow_control(connection):
    """Disable DTR/RTS hardware flow control lines."""
    connection.dtr = False
    connection.rts = False
    time.sleep(0.5)
```

**Applied in two places:**

### 2a. In `supported()` — for device probing

Added `cls._disable_flow_control(connection)` right after the `serial_connection` context manager opens:

```python
with serial_connection(device['identifier'], protocol, is_probing=True) as connection:
    cls._disable_flow_control(connection)  # <-- ADDED
    _logger.info(...)
```

### 2b. New `_take_measure()` override — for weight reading

```python
def _take_measure(self):
    """Apply flow control fix before first measurement."""
    if self._connection and self._connection.dtr:
        self._disable_flow_control(self._connection)
    super()._take_measure()
```

**Why:** pyserial's `serial.Serial()` sets DTR and RTS high by default when opening a port. Some FTDI USB-to-serial adapters (the standard chipset on Pi IoT Boxes) won't pass data to the CPWplus with these lines asserted. The scale responds with empty bytes (`b''`).

Odoo's `serial_connection()` context manager only passes `baudrate`, `bytesize`, `stopbits`, `parity`, `timeout`, and `writeTimeout` to `serial.Serial()` — there's no way to pass `dsrdtr=False` or configure DTR/RTS through the protocol definition.

**How we diagnosed it:**
- `stty raw` + `echo G > /dev/ttyUSB0` worked (raw OS-level I/O doesn't set DTR/RTS)
- `os.open()` + `os.write()` worked
- `serial.Serial()` with defaults returned `b''`
- `serial.Serial()` with `dsrdtr=False, rtscts=False` + `s.dtr=False; s.rts=False` returned weight data

---

## Change 3: Fix data key from `value` to `result` in `AdamCPWplusDriver.py`

**In `_read_weight()` method, two occurrences:**

```python
# OLD:
self.data = {
    'value': weight,
    'status': self._status,
}
# ...
self.data = {
    'value': self.data.get('value', 0),
    'status': self._status,
}

# NEW:
self.data = {
    'result': weight,
    'status': self._status,
}
# ...
self.data = {
    'result': self.data.get('result', 0),
    'status': self._status,
}
```

**Why:** Odoo 19's `ScaleDriver._take_measure()` reads `self.data['result']` (line 147 of `serial_scale_driver.py`). The old API used `'value'`.

**Error before fix:**
```
KeyError: 'result'
  File "serial_scale_driver.py", line 147, in _take_measure
    if self.data['result'] != self.last_sent_value
```

---

## Change 4: Fix install paths in `install.sh`

**Lines 22-23**

```bash
# OLD:
PERSISTENT_DIR="/root_bypass_ramdisks/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"
ACTIVE_DIR="/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"

# NEW:
PERSISTENT_DIR="/root_bypass_ramdisks/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers"
ACTIVE_DIR="/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers"
```

---

## Change 5: Fix deploy paths in `deploy.sh`

**Lines 28-29**

```bash
# OLD:
PERSISTENT_DIR="/root_bypass_ramdisks/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"
ACTIVE_DIR="/home/pi/odoo/addons/hw_drivers/iot_handlers/drivers"

# NEW:
PERSISTENT_DIR="/root_bypass_ramdisks/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers"
ACTIVE_DIR="/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers"
```

---

## Files Modified

| File | Changes |
|------|---------|
| `AdamCPWplusDriver.py` | Import paths, DTR/RTS fix, `value` → `result` |
| `install.sh` | `hw_drivers` → `iot_drivers` in directory paths |
| `deploy.sh` | `hw_drivers` → `iot_drivers` in directory paths |

## Deployment Notes

- `deploy.sh` fails silently when `sshpass` is not installed due to `set -euo pipefail` — the remount SSH command returns non-zero and kills the script
- Manual deploy workaround:
  ```bash
  scp AdamCPWplusDriver.py pi@<IP>:/tmp/
  ssh pi@<IP> "sudo cp /tmp/AdamCPWplusDriver.py /home/pi/odoo/addons/iot_drivers/iot_handlers/drivers/"
  ssh pi@<IP> "sudo cp /tmp/AdamCPWplusDriver.py /root_bypass_ramdisks/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers/"
  ssh pi@<IP> "sudo systemctl restart odoo"
  ```

## Change 6: Fix POS Scale Hang — `_do_action()` Override

**Status:** Fixed (2026-02-10)

### Problem

The POS "get weight" and "tare" buttons hung — the scale popup spun forever even though the IoT Box logs showed the action completing.

### Root Cause

The original `action()` override bypassed the parent `SerialDriver.action()` which handles three critical things:

1. `self.data["owner"] = data.get('session_id')` — tags response with POS session
2. `self.data["action_args"] = {**data}` — stores action context
3. `event_manager.device_changed(self, data)` — notifies POS via long polling

Without step 3, POS never received the result.

### Fix

Override `_do_action()` instead of `action()`. This preserves the parent's session tracking and event notification flow:

```python
def _do_action(self, data):
    """Apply DTR/RTS flow control fix before executing any POS action."""
    if self._connection and self._connection.dtr:
        self._disable_flow_control(self._connection)
    super()._do_action(data)
```

**Why this works:**
- Parent `action()` handles session tagging, connection management, and `event_manager.device_changed()`
- Parent `action()` calls `_do_action()` with the connection already open
- Our override intercepts, disables DTR/RTS if needed, then delegates to `super()._do_action()`
- No `event_manager` import needed — the parent handles notification

Also added a `_take_measure()` override for the same DTR/RTS fix during continuous weight reading:

```python
def _take_measure(self):
    """Apply flow control fix before measurement."""
    if self._connection and self._connection.dtr:
        self._disable_flow_control(self._connection)
    super()._take_measure()
```

---

## Verification

After deploying, check logs for:
```
Probing /dev/ttyUSB0 with protocol Adam CPWplus
Probe response from /dev/ttyUSB0: b'+  0.12  lb\r\n'
CPWplus identified on /dev/ttyUSB0
```

The scale should appear as "Adam CPWplus" on the IoT Box homepage at `http://<IP>:8069`.
