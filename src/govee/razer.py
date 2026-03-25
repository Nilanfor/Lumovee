"""
govee.razer - Dreamview (razer) per-segment control for the Govee H6609.

Reverse-engineered from Govee Desktop LAN traffic captured via capture.py.
Protocol: cmd=razer, binary payload base64-encoded, XOR checksum.
"""

import base64

from .device import _send, _xor

# --- Protocol constants ---
_HEADER      = bytes([0xbb, 0x00, 0x86, 0xb4, 0x00])
_CTRL_PREFIX = bytes([0xbb, 0x00, 0x01, 0xb1])

# --- Physical layout (H6609, 33 segments × 3 LEDs = 99 LEDs) ---
# Segment 0: bottom of left side; indices increase clockwise.
# Corner segments straddle the bend — their 3 LEDs light up both adjacent sides.
# These three corners also correspond to flag=2 bytes in the wire protocol.
#
#          TOP  (12 segs, 6–17)
#   LEFT  ┌─────────────────────────┐ RIGHT
#   0–5   │                         │  18–23
#         └────────────── ctrl ─────┘
#          BOTTOM (9 segs, 24–32)
#
NUM_SEGMENTS = 33
SEGS_LEFT    = list(range(0,  6))   # 6 segs, bottom→top
SEGS_TOP     = list(range(6,  18))  # 12 segs, left→right
SEGS_RIGHT   = list(range(18, 24))  # 6 segs, top→bottom
SEGS_BOTTOM  = list(range(24, 33))  # 9 segs, right→left (controller at end)
SEGS_CORNERS = [5, 16, 21]          # top-left, top-right, bottom-right

_CORNERS_SET = frozenset(SEGS_CORNERS)


# --- Internal helpers ---

def _ctrl_pt(enable: bool) -> str:
    body = _CTRL_PREFIX + bytes([0x01 if enable else 0x00])
    return base64.b64encode(body + bytes([_xor(body)])).decode()


def _frame_pt(segment_colors: list) -> str:
    body = _HEADER + bytes([len(segment_colors)])
    for i, (r, g, b) in enumerate(segment_colors):
        body += bytes([r, g, b, 2 if i in _CORNERS_SET else 1])
    return base64.b64encode(body + bytes([_xor(body)])).decode()


# --- Public API ---

def razer_start(ip: str):
    """Enable Dreamview mode — must be called before sending color frames."""
    _send(ip, "razer", {"pt": _ctrl_pt(True)})


def razer_stop(ip: str):
    """Disable Dreamview mode."""
    _send(ip, "razer", {"pt": _ctrl_pt(False)})


def set_segments_razer(ip: str, segment_colors: list):
    """
    Set per-segment colors via the razer protocol.
    segment_colors: list of (R, G, B) tuples, length NUM_SEGMENTS (33).
    """
    if len(segment_colors) != NUM_SEGMENTS:
        raise ValueError(f"Expected {NUM_SEGMENTS} segments, got {len(segment_colors)}")
    _send(ip, "razer", {"pt": _frame_pt(segment_colors)})
