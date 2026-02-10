# -*- coding: utf-8 -*-
# Part of Henderson Farm Store IoT configuration.
# License: LGPL-3 (matching Odoo's IoT handler license)
#
# Driver for Adam Equipment CPWplus floor scales connected via RS-232.
# Designed for deployment to an Odoo IoT Box (Raspberry Pi).
#
# The built-in AdamEquipmentDriver targets the AZExtra series and uses
# baud 4800, a kg-only regex, and a 5-second delay (the AZExtra beeps).
# The CPWplus differs: baud 9600, multi-unit output (lb/kg/oz), no beep,
# and a weight response pattern that allows positive probing.
#
# CPWplus RS-232 command reference (from CPWplus User Manual):
#   G  -> Gross weight   Response: "+  5.00  lb\r\n"
#   N  -> Net weight     Response: "+  5.00  lb\r\n"
#   T  -> Tare           Response: echoes current weight
#   Z  -> Zero           Response: "<Z\r\n"
#   P  -> Print (same as G but labelled for printers)
#
# Response format:  [+|-]  <weight>  <unit>\r\n
#   where unit is one of: lb, kg, oz
# Note: Some firmware versions include a G/W or N/W prefix; ours does not.

import logging
import re
import serial
import time

from odoo.addons.iot_drivers.iot_handlers.drivers.serial_base_driver import (
    SerialProtocol,
    serial_connection,
)
from odoo.addons.iot_drivers.iot_handlers.drivers.serial_scale_driver import ScaleDriver

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol definition for Adam Equipment CPWplus
# ---------------------------------------------------------------------------
# The regex captures the numeric weight from responses like:
#   "G/W  + 5.00 lb\r\n"    (gross weight in pounds)
#   "N/W  - 0.50 kg\r\n"    (net weight in kilograms)
#   "G/W  +  12.5 oz\r\n"   (gross weight in ounces)
#
# Pattern breakdown:
#   (?:[GN]/W\s*)? - optional G/W (gross) or N/W (net) prefix
#   [+-]        - sign character
#   \s*         - optional whitespace
#   ([0-9.]+)   - the numeric weight (primary capture group)
#   \s+         - whitespace before unit
#   (lb|kg|oz)  - unit suffix
#
# Note: The G/W prefix is optional because some CPWplus firmware versions
# omit it, sending "+  0.58  lb\r\n" instead of "G/W  + 0.58 lb\r\n".
# The base ScaleDriver._read_weight() only reads group(1) from
# measureRegexp. So we put the number in group(1) and handle the sign
# separately in our _read_weight() override.
#
# Simplified regex for measureRegexp (group 1 = weight number):
CPW_MEASURE_REGEXP = rb"(?:[GN]/W\s*)?[+-]\s*([0-9.]+)\s+(?:lb|kg|oz)"

# Separate pattern to detect negative sign (used in _read_weight override):
CPW_SIGN_REGEXP = rb"(?:[GN]/W\s*)?(-)\s*[0-9.]"

CPWplusProtocol = SerialProtocol(
    name='Adam CPWplus',
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    stopbits=serial.STOPBITS_ONE,
    parity=serial.PARITY_NONE,
    timeout=1,
    writeTimeout=1,
    measureRegexp=CPW_MEASURE_REGEXP,
    statusRegexp=None,
    commandTerminator=b'\r\n',
    commandDelay=0.2,
    measureDelay=0.5,
    newMeasureDelay=0.5,       # CPWplus doesn't beep — no need for 5s delay
    measureCommand=b'G',        # Gross weight request
    emptyAnswerValid=False,     # CPWplus always responds to G command
)


class AdamCPWplusDriver(ScaleDriver):
    """Driver for Adam Equipment CPWplus series floor scales.

    Extends the base ScaleDriver with:
    - CPWplus-specific serial protocol (9600 baud, multi-unit regex)
    - Positive device identification via G command probing
    - Tare and Zero actions wired to the frontend
    - Negative weight handling
    """

    _protocol = CPWplusProtocol
    priority = 10  # Higher than built-in AdamEquipmentDriver (priority=0)

    @staticmethod
    def _disable_flow_control(connection):
        """Disable DTR/RTS hardware flow control lines.

        FTDI USB-to-serial adapters on Pi IoT Boxes set DTR/RTS high by
        default, which prevents the CPWplus from responding over RS-232.
        """
        connection.dtr = False
        connection.rts = False
        time.sleep(0.5)

    def __init__(self, identifier, device):
        super().__init__(identifier, device)
        self.device_manufacturer = 'Adam'

    def _set_actions(self):
        """Extend parent actions with tare and zero commands."""
        super()._set_actions()
        self._actions.update({
            'tare': self._tare_action,
            'zero': self._zero_action,
        })

    def _tare_action(self, data):
        """Send tare command to zero out container weight."""
        self._connection.write(b'T' + self._protocol.commandTerminator)
        time.sleep(self._protocol.commandDelay)
        _logger.info('CPWplus: Tare command sent')

    def _zero_action(self, data):
        """Send zero command to re-zero the scale."""
        self._connection.write(b'Z' + self._protocol.commandTerminator)
        time.sleep(self._protocol.commandDelay)
        _logger.info('CPWplus: Zero command sent')

    # ------------------------------------------------------------------
    # Device identification
    # ------------------------------------------------------------------
    @classmethod
    def supported(cls, device):
        """Probe the serial device to determine if it is a CPWplus.

        Sends a Gross weight command ('G') and checks for the distinctive
        'G/W' prefix in the response. This positively identifies a CPWplus
        (or compatible Adam scale) versus other serial devices.

        :param device: device info dict with 'identifier' key (serial port path)
        :type device: dict
        :return: True if the device responds like a CPWplus
        :rtype: bool
        """
        protocol = cls._protocol

        try:
            with serial_connection(device['identifier'], protocol, is_probing=True) as connection:
                cls._disable_flow_control(connection)
                _logger.info(
                    'Probing %s with protocol %s',
                    device['identifier'], protocol.name,
                )
                # Send Gross weight request
                connection.write(b'G' + protocol.commandTerminator)
                time.sleep(protocol.commandDelay)

                # Read response — CPWplus returns ~20 chars like "G/W  + 5.00 lb\r\n"
                answer = connection.read(30)
                _logger.info(
                    'Probe response from %s: %r',
                    device['identifier'], answer,
                )

                # Check for G/W prefix (some firmware) or weight
                # pattern without prefix (e.g. "+  0.58  lb\r\n")
                if (b'G/W' in answer or b'N/W' in answer
                        or re.search(rb'[+-]\s*[0-9.]+\s+(?:lb|kg|oz)', answer)):
                    _logger.info(
                        'CPWplus identified on %s', device['identifier'],
                    )
                    return True
                else:
                    _logger.info(
                        'No CPWplus signature in response from %s: %r',
                        device['identifier'], answer,
                    )

        except serial.serialutil.SerialTimeoutException:
            _logger.debug(
                'Serial timeout probing %s with %s',
                device['identifier'], protocol.name,
            )
        except Exception:
            _logger.exception(
                'Error probing %s with protocol %s',
                device['identifier'], protocol.name,
            )
        return False

    # ------------------------------------------------------------------
    # DTR/RTS fix for continuous measurement and POS actions
    # ------------------------------------------------------------------
    def _take_measure(self):
        """Apply flow control fix before measurement."""
        if self._connection and self._connection.dtr:
            self._disable_flow_control(self._connection)
        super()._take_measure()

    def _do_action(self, data):
        """Apply DTR/RTS flow control fix before executing any POS action."""
        if self._connection and self._connection.dtr:
            self._disable_flow_control(self._connection)
        super()._do_action(data)

    # ------------------------------------------------------------------
    # Weight reading with negative sign handling
    # ------------------------------------------------------------------
    def _read_weight(self):
        """Read weight from the scale, handling the +/- sign.

        The base class regex captures only the numeric portion (group 1).
        We override to also detect the sign character and negate the value
        when the scale reports a negative weight (e.g., after tare with
        nothing on the platform).
        """
        protocol = self._protocol
        self._connection.write(protocol.measureCommand + protocol.commandTerminator)
        answer = self._get_raw_response(self._connection)

        match = re.search(protocol.measureRegexp, answer)
        if match:
            weight = float(match.group(1))

            # Check for negative sign
            sign_match = re.search(CPW_SIGN_REGEXP, answer)
            if sign_match:
                weight = -weight

            self.data = {
                'result': weight,
                'status': self._status,
            }
        else:
            # No valid weight in response — log for debugging
            if answer:
                _logger.debug('CPWplus: no weight match in response: %r', answer)
            self.data = {
                'result': self.data.get('result', 0),
                'status': self._status,
            }

    def _read_status(self, answer):
        """CPWplus doesn't send separate status bytes — no-op."""
        pass
