"""
router.py - Headless CLI router: forwards Hyperion / HyperHDR UDP Raw frames to the Govee strip.

The GUI application (src/ui.py) supersedes this script for normal use.
This is kept as a lightweight fallback for headless / server environments.

Input:  UDP Raw on 0.0.0.0:5568
        Packet format: [R0,G0,B0, R1,G1,B1, ..., Rn,Gn,Bn]  (3 bytes per LED, no headers)
        Compatible with Hyperion and HyperHDR "udpraw" output.

Output: Govee H6609 via Razer/DreamView LAN protocol.

Usage:
  python tools/router.py
"""

import socket
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from govee import discover, DEVICE_SKU, turn_on, set_brightness
from govee import razer_start, razer_stop, set_segments_razer, NUM_SEGMENTS

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5568


def _parse(data: bytes) -> list[tuple[int, int, int]] | None:
    if not data or len(data) % 3 != 0:
        return None
    return [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]


def main():
    print("Discovering Govee device...")
    ip = discover(sku=DEVICE_SKU)
    if not ip:
        print("Device not found. Close Govee Desktop or set DEVICE_IP in src/govee/device.py.")
        sys.exit(1)
    print(f"Device at {ip}")

    turn_on(ip)
    set_brightness(ip, 100)
    razer_start(ip)
    print("Razer mode enabled.")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((LISTEN_HOST, LISTEN_PORT))
    sock.settimeout(5)
    print(f"Listening on :{LISTEN_PORT} → Govee {ip}  (Ctrl+C to stop)\n")

    frames = 0
    try:
        while True:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue

            leds = _parse(data)
            if leds is None:
                continue
            if len(leds) != NUM_SEGMENTS:
                print(f"  Unexpected LED count {len(leds)}, expected {NUM_SEGMENTS} — skipping")
                continue

            set_segments_razer(ip, leds)
            frames += 1
            if frames % 100 == 0:
                print(f"  {frames} frames forwarded")

    except KeyboardInterrupt:
        print(f"\nStopped after {frames} frames.")
    finally:
        sock.close()
        razer_stop(ip)
        print("Razer mode disabled.")


if __name__ == "__main__":
    main()
