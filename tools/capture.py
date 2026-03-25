"""
capture.py - Capture UDP packets sent from Govee Desktop to the device.

Run as Administrator (required for raw socket / promiscuous mode).

Usage:
  1. Close any other script using the device.
  2. Open Govee Desktop and start Dreamview on the monitor backlight.
  3. Run:  python tools/capture.py
  4. Paste the output here so we can decode the exact packet format.
"""

import socket
import struct
import base64
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from govee import discover, DEVICE_SKU

DEVICE_IP = None   # resolved dynamically via LAN discovery; fallback below
CMD_PORT  = 4003   # only used for annotation; capture checks all ports
_FALLBACK_IP = "192.168.2.116"


def _decode_packet(payload: bytes):
    try:
        msg = json.loads(payload.decode())
        cmd = msg.get("msg", {}).get("cmd")
        data = msg.get("msg", {}).get("data", {})
        if cmd == "ptReal":
            cmds = data.get("command", [])
            lines = [f"  cmd=ptReal  ({len(cmds)} sub-packets)"]
            for i, pkt in enumerate(cmds):
                raw = base64.b64decode(pkt)
                lines.append(f"    [{i}] {raw.hex()}  ({list(raw[:6])}...)")
            return "\n".join(lines)
        return f"  cmd={cmd}  data={json.dumps(data)}"
    except Exception:
        return f"  raw hex: {payload.hex()}"


def capture(device_ip=DEVICE_IP):
    if not device_ip:
        print(f"Discovering {DEVICE_SKU} on LAN...")
        device_ip = discover(sku=DEVICE_SKU)
        if device_ip:
            print(f"Found device at {device_ip}")
        else:
            print(f"Discovery failed — falling back to {_FALLBACK_IP}")
            device_ip = _FALLBACK_IP

    # Find the local interface IP that routes to the device (same subnet).
    # SIO_RCVALL on Windows requires binding to a specific interface, not 0.0.0.0.
    try:
        _probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _probe.connect((device_ip, 80))
        local_ip = _probe.getsockname()[0]
        _probe.close()
    except Exception:
        local_ip = "0.0.0.0"
    print(f"Local interface: {local_ip}")

    # Use IP_HDRINCL raw socket to capture ALL IP traffic (UDP + TCP)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
    except PermissionError:
        print("ERROR: raw socket requires Administrator. Re-run as admin.")
        sys.exit(1)

    # Promiscuous mode — on Windows must bind to the specific local interface IP.
    try:
        s.bind((local_ip, 0))
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        print("Promiscuous mode enabled (outgoing packets will be captured).")
    except Exception as e:
        print(f"WARNING: could not enable promiscuous mode: {e}")
        print("         Only incoming packets will be captured.")

    s.settimeout(120)
    print(f"Capturing ALL traffic to/from {device_ip} — start Dreamview now.")
    print("Press Ctrl+C to stop.\n")

    count = 0
    try:
        while True:
            try:
                data = s.recv(65535)
            except socket.timeout:
                print("(timeout — no packets in 120 s)")
                break

            if len(data) < 20:
                continue

            # IP header: variable length encoded in lower nibble of byte 0, in 32-bit words
            ihl = (data[0] & 0x0F) * 4
            proto = data[9]  # 6=TCP, 17=UDP
            src_ip = socket.inet_ntoa(data[12:16])
            dst_ip = socket.inet_ntoa(data[16:20])

            if dst_ip != device_ip and src_ip != device_ip:
                continue

            if len(data) < ihl + 4:
                continue

            # Both TCP and UDP have src port at ihl+0, dst port at ihl+2
            src_port = struct.unpack("!H", data[ihl:ihl+2])[0]
            dst_port = struct.unpack("!H", data[ihl+2:ihl+4])[0]
            proto_name = {6: "TCP", 17: "UDP"}.get(proto, f"proto={proto}")

            direction = "→" if dst_ip == device_ip else "←"
            count += 1
            print(f"=== Packet {count} | {proto_name} {src_ip}:{src_port} {direction} {dst_ip}:{dst_port} ({len(data)-ihl-8} payload bytes) ===")

            if proto == 17:  # UDP — try to decode as Govee JSON
                payload = data[ihl+8:]
                print(_decode_packet(payload))
            elif proto == 6:  # TCP — just show raw start
                payload = data[ihl+20:]  # skip TCP header (min 20 bytes)
                if payload:
                    print(f"  raw hex: {payload[:64].hex()}")
            print()

    except KeyboardInterrupt:
        print(f"\nStopped after {count} packets.")
    finally:
        try:
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        except Exception:
            pass
        s.close()


if __name__ == "__main__":
    capture()
