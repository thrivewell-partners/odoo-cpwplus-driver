# -*- coding: utf-8 -*-
# Part of Henderson Farm Store IoT configuration.
# License: LGPL-3 (matching Odoo's IoT handler license)
#
# Driver for Adam Equipment CPWplus floor scales connected via RS-232.
# Designed for deployment to an Odoo IoT Box (Raspberry Pi).

import logging
import re
import serial
import time

from odoo.addons.iot_drivers.event_manager import event_manager
from odoo.addons.iot_drivers.iot_handlers.drivers.serial_base_driver import (
    SerialProtocol,
    serial_connection,
)
from odoo.addons.iot_drivers.iot_handlers.drivers.serial_scale_driver import ScaleDriver

_logger = logging.getLogger(__name__)

CPW_MEASURE_REGEXP = rb"(?:[GN]/W\s*)?[+-]\s*([0-9.]+)\s+(?:lb|kg|oz)"
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
    newMeasureDelay=0.5,
    measureCommand=b'G',
    emptyAnswerValid=False,
)


class AdamCPWplusDriver(ScaleDriver):
    """Driver for Adam Equipment CPWplus series floor scales.

    Extends ScaleDriver with:
    - DTR/RTS flow control fix for FTDI USB-to-serial adapters
    - Fast CR/LF-terminated serial reads
    - Tare and zero commands
    - Action response with status:'success' for POS compatibility
    """

    _protocol = CPWplusProtocol
    priority = 10

    @staticmethod
    def _disable_flow_control(connection):
        """Disable DTR/RTS — FTDI adapters set these high by default,
        which prevents the CPWplus from responding over RS-232."""
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
        self._connection.write(b'T' + self._protocol.commandTerminator)
        time.sleep(self._protocol.commandDelay)
        _logger.info('CPWplus: Tare command sent')

    def _zero_action(self, data):
        self._connection.write(b'Z' + self._protocol.commandTerminator)
        time.sleep(self._protocol.commandDelay)
        _logger.info('CPWplus: Zero command sent')

    @classmethod
    def supported(cls, device):
        protocol = cls._protocol
        try:
            with serial_connection(device['identifier'], protocol, is_probing=True) as connection:
                cls._disable_flow_control(connection)
                _logger.info('Probing %s with protocol %s', device['identifier'], protocol.name)
                connection.write(b'G' + protocol.commandTerminator)
                time.sleep(protocol.commandDelay)
                answer = connection.read(30)
                _logger.info('Probe response from %s: %r', device['identifier'], answer)
                if (b'G/W' in answer or b'N/W' in answer
                        or re.search(rb'[+-]\s*[0-9.]+\s+(?:lb|kg|oz)', answer)):
                    _logger.info('CPWplus identified on %s', device['identifier'])
                    return True
        except serial.serialutil.SerialTimeoutException:
            pass
        except Exception:
            _logger.exception('Error probing %s', device['identifier'])
        return False

    # ------------------------------------------------------------------
    # DTR/RTS fix — applied before any serial read
    # ------------------------------------------------------------------
    def _take_measure(self):
        """Base ScaleDriver._take_measure with DTR/RTS fix."""
        if self._connection and self._connection.dtr:
            self._disable_flow_control(self._connection)
        super()._take_measure()

    def _do_action(self, data):
        """Base SerialDriver._do_action with DTR/RTS fix."""
        if self._connection and self._connection.dtr:
            self._disable_flow_control(self._connection)
        super()._do_action(data)

    # ------------------------------------------------------------------
    # Action override — POS expects status:'success' in action events.
    # Base SerialDriver.action() sends status as a dict (e.g.
    # {'status': 'connected', ...}) which POS doesn't recognize as
    # a completed action, causing the UI to hang.  We inject
    # status:'success' into the event data (not self.data) so the
    # continuous _take_measure loop is unaffected.
    # ------------------------------------------------------------------
    def action(self, data):
        self.data["owner"] = data.get('session_id')
        self.data["action_args"] = {**data}

        if self._connection and self._connection.isOpen():
            self._do_action(data)
        else:
            with serial_connection(self.device_identifier, self._protocol) as connection:
                self._connection = connection
                self._do_action(data)

        # Merge status:'success' into event data — **data is applied last
        # in event_manager.device_changed so this overwrites self.data's
        # status dict, while leaving self.data untouched for _take_measure.
        response_data = {**data, 'status': 'success'}
        event_manager.device_changed(self, response_data)

    # ------------------------------------------------------------------
    # Weight reading — fast \r\n-terminated read with sign handling
    # ------------------------------------------------------------------
    def _read_weight(self):
        protocol = self._protocol
        self._connection.write(protocol.measureCommand + protocol.commandTerminator)
        time.sleep(protocol.measureDelay)

        answer = b''
        while len(answer) < 40:
            byte = self._connection.read(1)
            if not byte:
                break
            answer += byte
            if answer.endswith(b'\r\n'):
                break

        match = re.search(protocol.measureRegexp, answer)
        if match:
            weight = float(match.group(1))
            sign_match = re.search(CPW_SIGN_REGEXP, answer)
            if sign_match:
                weight = -weight
            self.data = {
                'value': weight,
                'result': weight,
                'status': self._status,
            }
        else:
            _logger.warning('CPWplus: NO MATCH raw=%r', answer)
            self.data = {
                'value': self.data.get('result', 0),
                'result': self.data.get('result', 0),
                'status': self._status,
            }

    def _read_status(self, answer):
        pass
