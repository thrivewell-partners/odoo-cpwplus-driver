# Adam CPWplus Scale — POS Integration Troubleshooting

**Last updated:** 2026-02-10
**Status:** POS does not display weight from scale. Hangs or shows nothing depending on driver configuration.

---

## Hardware Setup

| Component | Details |
|-----------|---------|
| Scale | Adam Equipment CPWplus floor scale |
| Connection | RS-232 serial (9600 baud, 8N1) |
| Adapter | FTDI FT232R USB-to-serial (`/dev/ttyUSB0`) |
| IoT Box | Odoo 19 IoT Box on Raspberry Pi (aarch64) |
| IoT Box IP | 192.168.200.40 |
| Odoo Instance | henderson-farm-store.odoo.com (Odoo 19 Online / SaaS) |
| POS | POS 1 (pos.config id=1) |
| IoT Device | id=55, identifier `/dev/ttyUSB0`, type `scale` |

## What Works

- **Serial communication**: The driver reads weight from the scale correctly via RS-232. Confirmed via logs showing parsed weights (e.g., `0.994`, `1.8`).
- **DTR/RTS fix**: FTDI adapters set DTR/RTS high by default, blocking CPWplus responses. Disabling them resolves this.
- **Fast `_read_weight`**: Custom byte-by-byte read until `\r\n` terminator completes in ~50ms vs ~1.1s for the base `_get_raw_response` (which reads until timeout).
- **`/hw_proxy/scale_read`**: The Community edition HTTP endpoint returns correct weight: `{"weight": 1.8}`.
- **Driver detection**: `supported()` probe correctly identifies the CPWplus on `/dev/ttyUSB0`.
- **Action receipt**: IoT Box logs confirm actions are received via WebRTC and processed (action starts, weight read, action finishes in ~1s).

## The Core Problem

**POS sends a "Get Weight" action but never displays the weight.** Two failure modes:

### Failure Mode 1: POS Hangs (spinning forever)
- **When**: Using base `SerialDriver.action()` behavior (no override)
- **Why**: `SerialDriver.action()` sends an event with `status: {'status': 'connected', ...}` (a dict). POS JavaScript expects `status: 'success'` (a string) to resolve the action promise. Without it, POS waits indefinitely.

### Failure Mode 2: No Hang, But No Weight Displayed
- **When**: Overriding `action()` to include `status: 'success'` in the event
- **Why**: Unknown. POS receives the event (no hang = promise resolved), but doesn't render the weight. Both `value` and `result` fields contain the correct weight float.

**This is the catch-22**: `status: 'success'` is required to prevent the hang, but even with it, POS doesn't display the weight.

---

## Architecture: How Weight Gets to POS

Understanding the event flow is critical. There are several paths:

### POS → IoT Box (Action Request)
```
POS JavaScript
  → WebRTC data channel (primary)
  → webrtc_client.py receives "iot_action" message
  → calls device.action(data) in a thread executor
  → RETURN VALUE IS DISCARDED (never sent back)
```

### IoT Box → POS (Events)
```
event_manager.device_changed(device, data=None)
  constructs: {**device.data, 'device_identifier': ..., 'time': ..., **data}
  sends via THREE paths simultaneously:
    1. webrtc_client.send() → WebRTC data channels → POS
    2. send_to_controller() → HTTP POST to henderson-farm-store.odoo.com/iot/box/send_websocket → Odoo bus → POS
    3. Longpolling sessions (for /iot_drivers/event route)
```

### Key Insight
The return value of `device.action()` is **always discarded** by the WebRTC handler. Weight reaches POS **only** through events from `event_manager.device_changed()`.

### Two Event Sources for Weight

1. **Action events** — `SerialDriver.action()` calls `event_manager.device_changed(self, data)` after `_do_action()` completes. Event includes `**data` (the raw request) merged on top.

2. **Measurement loop events** — `ScaleDriver._take_measure()` (called continuously in `run()` loop) calls `event_manager.device_changed(self)` when weight changes. No request data merged.

---

## Source Code Key Points

### `SerialDriver._push_status()` — Does NOT push events
```python
def _push_status(self):
    self.data['status'] = self._status  # Just updates self.data, no event!
```
Despite the name and docstring, this only updates `self.data['status']`. It does NOT call `event_manager`.

### `SerialDriver.action()` — Sends ONE event
```python
def action(self, data):
    self.data["owner"] = data.get('session_id')
    self.data["action_args"] = {**data}
    if self._connection and self._connection.isOpen():
        self._do_action(data)                    # synchronous
    else:
        with serial_connection(...) as connection:
            self._connection = connection
            self._do_action(data)
    event_manager.device_changed(self, data)      # THE ONLY event sent
```

### `ScaleDriver._take_measure()` — Pushes on weight change
```python
def _take_measure(self):
    with self._device_lock:
        self._read_weight()
        if self.data['result'] != self.last_sent_value or self._status['status'] == self.STATUS_ERROR:
            self.last_sent_value = self.data['result']
            event_manager.device_changed(self)    # No request data
```

### `ScaleDriver._read_weight()` — Base version sets only `result` (no `value`)
```python
self.data = {
    'result': float(match.group(1)),
    'status': self._status                        # This is a dict, not 'success'
}
```

### `Driver.__init__()` — Initial data format
```python
self.data = {'value': '', 'result': ''}
```

### `ScaleDriver._is_reading` — Set but never checked
The `start_reading`/`stop_reading` actions toggle `self._is_reading`, but the `_take_measure` loop runs unconditionally regardless.

### `ScaleDriver._set_actions()` — Registered actions
```python
'read_once'      → _read_once_action (reads weight once)
'start_reading'  → _start_reading_action (sets _is_reading = True)
'stop_reading'   → _stop_reading_action (sets _is_reading = False)
```

---

## All Driver Versions Tested

### Version 1: `status: 'success'` with value/result
**Override**: Custom `action()` that sets `self.data['status'] = 'success'` and sends event.
**Result**: No hang, but no weight displayed in POS.
**Event content**: `{value: weight, result: weight, status: 'success', action_args: {...}, ...}`

### Version 2: SerialDriver pattern (no status override)
**Override**: Removed `status: 'success'`, let base SerialDriver.action() send event.
**Result**: POS hangs.
**Event content**: `{result: weight, status: {'status': 'connected', ...}, action_args: {...}, ...}`

### Version 3: `status: 'success'` + `action_args` (matching Driver.action() format)
**Override**: Added `action_args` and `session_id` to match base `Driver.action()` return format.
**Result**: No hang, but no weight displayed.

### Version 4: Minimal driver (no action/take_measure overrides)
**Override**: Only DTR/RTS fix and fast `_read_weight`. Let base ScaleDriver/SerialDriver handle everything.
**Result**: POS hangs. Confirmed base behavior is incompatible.
**Logs showed**: Action received, processed in ~1s, completed. But POS still hung.

### Version 5: `status: 'success'` via response_data (race-condition safe)
**Override**: Injects `status: 'success'` into the event data dict (not self.data) so `_take_measure` loop is unaffected.
**Result**: POS hangs (user reported "system just hangs" — may be same Failure Mode 1 or a regression).

---

## Configuration Changes Tried

### `manual_measurement` (iot.device id=55)

| Setting | POS Behavior | Expected |
|---------|-------------|----------|
| `true` (default) | POS sends `read_once` on "Get Weight" button press | Single reading |
| `false` | POS should send `start_reading` and display live weight stream | Continuous reading |

Changed to `false` via API multiple times, but:
- It reverted to `true` at least once (possibly from IoT device re-registration on restart)
- User may not have fully refreshed POS to pick up the change
- **Never properly tested with `manual_measurement: false` + a refreshed POS session**

---

## Unresolved Questions

### 1. Why doesn't POS display weight when `status: 'success'` is present?
The event contains `value` and `result` with the correct weight. POS resolves the action (no hang). But the weight never appears in the UI. Possible causes:
- POS JavaScript reads weight from a **different field** than `value`/`result`
- POS JavaScript reads weight from a **different event** (e.g., a subsequent measurement event, not the action response)
- The Odoo server transforms the event before forwarding to POS via the bus, and the transformation drops or renames fields
- POS expects the weight in a specific **format** (string vs float, specific decimal places)

### 2. Why does `manual_measurement` keep reverting to `true`?
Possibly the IoT device re-registers on each Odoo service restart, and the server resets the field. Need to check if there's a server-side default or if the IoT Box sends device metadata that overwrites it.

### 3. Does the Toledo 8217 (recommended scale) actually work with `read_once`?
The Toledo 8217 driver uses the same `SerialDriver.action()` base code. If it also sends `status: {'status': 'connected', ...}`, then it would also hang with `read_once`. This suggests:
- Toledo might only work with `manual_measurement: false` (continuous reading)
- Or there's something different in how Toledo is configured/detected

### 4. What exactly does POS JavaScript expect in scale events?
The enterprise POS IoT JavaScript code (`pos_iot` module) is not accessible from the IoT Box. It lives in the Odoo enterprise codebase. Understanding what fields POS reads from scale events would definitively solve this.

### 5. Does the Odoo server transform events before forwarding to POS?
Events go through `send_to_controller()` → HTTP POST to `/iot/box/send_websocket` on the Odoo server. The server may modify the event structure before pushing it to POS clients via the bus. We haven't examined this server-side processing.

### 6. The 401 UNAUTHORIZED on `/iot/get_handlers`
Separate issue observed in IoT Box logs. The IoT Box gets 401 when trying to download handlers from the Odoo server. This may mean the handler download mechanism is broken, though the driver works when manually deployed.

---

## Recommended Next Steps

### Step 1: Read the POS IoT JavaScript (Enterprise Source)
**Priority: High**
The fastest path to resolution is understanding what the POS JavaScript expects. Look for:
- How POS handles `iot_action` responses for scales
- What event fields POS reads for weight display (`value`, `result`, `weight`, other?)
- How `manual_measurement` changes POS behavior
- Whether POS distinguishes between action response events and measurement events

**Where to look:**
- Odoo 19 Enterprise source: `addons/pos_iot/static/src/`
- Specifically JavaScript/TypeScript files related to scale handling
- GitHub: `github.com/odoo/enterprise` (requires Odoo Enterprise partner access)
- Alternative: Use browser DevTools on the POS page to inspect the IoT action handling code

### Step 2: Test `manual_measurement: false` Properly
**Priority: High**
This has never been properly tested because:
1. The setting kept reverting to `true`
2. POS was never fully refreshed after the change

To test:
1. Set `manual_measurement: false` on iot.device id=55
2. **Close the POS session entirely** (not just refresh — click the hamburger menu → Close)
3. Reopen POS from the Odoo backend
4. Verify in browser DevTools (Network tab) that POS sends `start_reading` (not `read_once`)
5. Open the scale dialog and check if weight appears live

### Step 3: Use Browser DevTools to Inspect Events
**Priority: High**
In the POS browser tab:
1. Open DevTools (F12) → Console
2. Look for WebRTC or IoT-related messages
3. When pressing "Get Weight", observe:
   - What action is sent (`read_once` vs `start_reading`)
   - What events are received back
   - What fields POS JavaScript accesses from the event
   - Any JavaScript errors in the console

### Step 4: Compare with a Working Toledo 8217 Setup
**Priority: Medium**
If possible, find documentation or logs from a working Mettler-Toledo Ariva-S setup:
- What does `manual_measurement` default to for Toledo?
- What events does POS receive from Toledo?
- Does Toledo work with `read_once` or only continuous reading?

### Step 5: Investigate `manual_measurement` Persistence
**Priority: Medium**
Determine why the setting reverts:
- Check if the IoT Box sends device metadata on restart that overwrites it
- Check if there's a default in the `iot.device` model definition
- Consider setting it via an automation rule to keep it pinned to `false`

### Step 6: Test Event Format Variations
**Priority: Low (try after Steps 1-3)**
If the POS source code is not accessible, try different event formats empirically:
- Weight as string: `'value': '1.800'` instead of `'value': 1.8`
- Weight in a `weight` field: `'weight': 1.8`
- Mimicking base Driver.action() return format exactly in the event
- Including `owner`, `session_id` at the top level

---

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| Driver (local) | `/media/tyler/128GB/odoo/drivers/adam-cpwplus/AdamCPWplusDriver.py` | Source being edited |
| Driver (deployed) | `/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers/AdamCPWplusDriver.py` | On IoT Box |
| SerialDriver | `/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers/serial_base_driver.py` | Base serial class |
| ScaleDriver | `/home/pi/odoo/addons/iot_drivers/iot_handlers/drivers/serial_scale_driver.py` | Base scale class |
| Driver (base) | `/home/pi/odoo/addons/iot_drivers/driver.py` | Base Driver class |
| Event Manager | `/home/pi/odoo/addons/iot_drivers/event_manager.py` | Event routing |
| WebRTC Client | `/home/pi/odoo/addons/iot_drivers/webrtc_client.py` | WebRTC communication |
| Websocket Client | `/home/pi/odoo/addons/iot_drivers/websocket_client.py` | Server communication |
| Controllers | `/home/pi/odoo/addons/iot_drivers/controllers/driver.py` | HTTP routes |

## SSH Access

```bash
# IoT Box regenerates password on every Odoo service restart
# Password is set via chpasswd during boot
# Use SSH_ASKPASS trick (no sshpass/expect on this system):
cat > /tmp/sshpass.sh << 'EOF'
#!/bin/bash
echo "<current-password>"
EOF
chmod +x /tmp/sshpass.sh
SSH_ASKPASS=/tmp/sshpass.sh SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
  ssh -o StrictHostKeyChecking=no pi@192.168.200.40 "command"
```

## Deploy Workflow

```bash
# 1. Edit driver locally
# 2. SCP to IoT Box
scp ... pi@192.168.200.40:/tmp/AdamCPWplusDriver.py
# 3. Copy to drivers directory
ssh ... "sudo cp /tmp/AdamCPWplusDriver.py /home/pi/odoo/addons/iot_drivers/iot_handlers/drivers/"
# 4. Restart Odoo (generates new password!)
ssh ... "sudo systemctl restart odoo"
# 5. Get new password from IoT Box homepage or logs
```
