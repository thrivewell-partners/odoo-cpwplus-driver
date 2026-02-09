#!/usr/bin/env python3
"""Standalone test script for CPWplus serial communication.

Run this on any machine with the CPWplus connected via USB-to-Serial adapter
to verify the serial protocol BEFORE deploying to the IoT Box.

Usage:
    python3 test_serial.py [/dev/ttyUSB0]

Requirements:
    pip install pyserial
"""

import re
import sys
import time

import serial

# --- Configuration (must match CPWplus scale settings) ---
BAUD_RATE = 9600
BYTE_SIZE = serial.EIGHTBITS
STOP_BITS = serial.STOPBITS_ONE
PARITY = serial.PARITY_NONE
TIMEOUT = 2  # seconds

# Regex matching CPWplus response format
WEIGHT_RE = rb"[GN]/W\s*[+-]\s*([0-9.]+)\s*(?:lb|kg|oz)"
SIGN_RE = rb"[GN]/W\s*(-)\s*[0-9.]"

# Default serial port
DEFAULT_PORT = '/dev/ttyUSB0'


def open_connection(port):
    """Open a serial connection to the scale."""
    conn = serial.Serial(
        port=port,
        baudrate=BAUD_RATE,
        bytesize=BYTE_SIZE,
        stopbits=STOP_BITS,
        parity=PARITY,
        timeout=TIMEOUT,
        writeTimeout=TIMEOUT,
    )
    print(f"Connected to {port} at {BAUD_RATE} baud")
    return conn


def read_response(conn):
    """Read all available bytes from the serial port."""
    time.sleep(0.3)
    answer = b''
    while True:
        chunk = conn.read(1)
        if not chunk:
            break
        answer += chunk
    return answer


def test_gross_weight(conn):
    """Send G command and parse the response."""
    print("\n--- Test: Gross Weight (G command) ---")
    conn.write(b'G\r\n')
    answer = read_response(conn)
    print(f"  Raw response: {answer!r}")
    print(f"  Decoded:      {answer.decode('ascii', errors='replace').strip()}")

    match = re.search(WEIGHT_RE, answer)
    if match:
        weight = float(match.group(1))
        sign_match = re.search(SIGN_RE, answer)
        if sign_match:
            weight = -weight
        print(f"  Parsed weight: {weight}")
        return True
    else:
        print("  WARNING: No weight match found in response!")
        return False


def test_net_weight(conn):
    """Send N command and parse the response."""
    print("\n--- Test: Net Weight (N command) ---")
    conn.write(b'N\r\n')
    answer = read_response(conn)
    print(f"  Raw response: {answer!r}")
    print(f"  Decoded:      {answer.decode('ascii', errors='replace').strip()}")

    match = re.search(WEIGHT_RE, answer)
    if match:
        weight = float(match.group(1))
        sign_match = re.search(SIGN_RE, answer)
        if sign_match:
            weight = -weight
        print(f"  Parsed weight: {weight}")
        return True
    else:
        print("  WARNING: No weight match found in response!")
        return False


def test_tare(conn):
    """Send T (tare) command."""
    print("\n--- Test: Tare (T command) ---")
    conn.write(b'T\r\n')
    answer = read_response(conn)
    print(f"  Raw response: {answer!r}")
    print(f"  Decoded:      {answer.decode('ascii', errors='replace').strip()}")
    print("  (Tare command sent — check scale display)")
    return True


def test_zero(conn):
    """Send Z (zero) command."""
    print("\n--- Test: Zero (Z command) ---")
    conn.write(b'Z\r\n')
    answer = read_response(conn)
    print(f"  Raw response: {answer!r}")
    print(f"  Decoded:      {answer.decode('ascii', errors='replace').strip()}")
    print("  (Zero command sent — check scale display)")
    return True


def test_probe(conn):
    """Simulate the supported() probing logic."""
    print("\n--- Test: Device Probe (simulating supported()) ---")
    conn.write(b'G\r\n')
    time.sleep(0.2)
    answer = conn.read(30)
    print(f"  Probe response: {answer!r}")

    if b'G/W' in answer:
        print("  RESULT: CPWplus IDENTIFIED (G/W found)")
        return True
    elif b'N/W' in answer:
        print("  RESULT: CPWplus IDENTIFIED (N/W found)")
        return True
    else:
        print("  RESULT: NOT identified as CPWplus")
        return False


def continuous_read(conn, duration=10):
    """Continuously read weight for the specified duration."""
    print(f"\n--- Continuous Weight Reading ({duration}s) ---")
    print("  Place/remove items on the scale to test...")
    start = time.time()
    while time.time() - start < duration:
        conn.write(b'G\r\n')
        answer = read_response(conn)
        match = re.search(WEIGHT_RE, answer)
        if match:
            weight = float(match.group(1))
            sign_match = re.search(SIGN_RE, answer)
            if sign_match:
                weight = -weight
            print(f"  Weight: {weight:>10.2f}  (raw: {answer.strip()!r})")
        else:
            print(f"  No match   (raw: {answer.strip()!r})")
        time.sleep(0.5)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT

    print("=" * 60)
    print("  Adam CPWplus Serial Communication Test")
    print("=" * 60)
    print(f"  Port: {port}")
    print(f"  Baud: {BAUD_RATE}")
    print(f"  Config: {BYTE_SIZE}N1")

    try:
        conn = open_connection(port)
    except serial.SerialException as e:
        print(f"\nERROR: Could not open {port}: {e}")
        print("\nTroubleshooting:")
        print("  - Is the USB-to-Serial adapter plugged in?")
        print("  - Check available ports: python3 -m serial.tools.list_ports")
        print("  - Permission issue? Try: sudo chmod 666 " + port)
        sys.exit(1)

    try:
        passed = 0
        total = 0

        # Run tests
        for test_fn in [test_probe, test_gross_weight, test_net_weight, test_tare, test_zero]:
            total += 1
            try:
                if test_fn(conn):
                    passed += 1
            except Exception as e:
                print(f"  ERROR: {e}")

        print("\n" + "=" * 60)
        print(f"  Results: {passed}/{total} tests passed")
        print("=" * 60)

        # Optional continuous reading
        if passed > 0:
            try:
                input("\nPress Enter for 10s continuous reading (Ctrl+C to skip)...")
                continuous_read(conn)
            except (KeyboardInterrupt, EOFError):
                pass

    finally:
        conn.close()
        print("\nConnection closed.")


if __name__ == '__main__':
    main()
