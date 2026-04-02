"""
govee.device - LAN UDP control for Govee lights.

Discovery, basic commands (power, brightness, colour),
and ptReal/graffiti per-segment control.
"""

import socket
import json
import base64
import time

# --- Configuration ---
DEVICE_SKU = "H6609"
DEVICE_IP  = None   # set manually if discovery fails, e.g. "192.168.1.42"

_SCAN_PORT = 4001
_RECV_PORT = 4002
_CMD_PORT  = 4003
_MULTICAST = "239.255.255.250"


# --- Transport ---

_cmd_sock: socket.socket | None = None


def _get_cmd_sock() -> socket.socket:
    global _cmd_sock
    if _cmd_sock is None:
        _cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return _cmd_sock


def _send(ip: str, cmd: str, data: dict):
    global _cmd_sock
    msg = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
    try:
        _get_cmd_sock().sendto(msg, (ip, _CMD_PORT))
    except OSError:
        # Socket may be stale (e.g. WSAENOBUFS on Windows); recreate and retry once.
        try:
            _cmd_sock.close()
        except Exception:
            pass
        _cmd_sock = None
        _get_cmd_sock().sendto(msg, (ip, _CMD_PORT))


def _xor(data: bytes) -> int:
    v = 0
    for b in data:
        v ^= b
    return v


# --- Discovery ---

def _open_recv_sock(timeout: float):
    """Bind the discovery receive socket; return it or None on failure."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", _RECV_PORT))
    except PermissionError:
        sock.close()
        return None
    sock.settimeout(timeout)
    return sock


def _broadcast_scan():
    """Send the scan broadcast to all local interfaces."""
    scan_msg = json.dumps({
        "msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}
    }).encode()
    all_ips = list(dict.fromkeys(
        info[4][0]
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    ))
    targets = [_MULTICAST, "255.255.255.255"]
    for ip in all_ips:
        targets.append(ip.rsplit(".", 1)[0] + ".255")
    for target in targets:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(scan_msg, (target, _SCAN_PORT))
        except Exception:
            pass


def discover_all(timeout: float = 5.0) -> list[dict]:
    """Scan LAN; return list of {sku, ip} for every responding Govee device."""
    recv_sock = _open_recv_sock(timeout)
    if recv_sock is None:
        return []
    _broadcast_scan()
    devices: dict[str, dict] = {}
    try:
        while True:
            data, addr = recv_sock.recvfrom(4096)
            try:
                msg = json.loads(data.decode())
                d = msg.get("msg", {}).get("data", {})
                ip = d.get("ip", addr[0])
                if ip not in devices:
                    devices[ip] = {"sku": d.get("sku", "?"), "ip": ip}
            except json.JSONDecodeError:
                pass
    except socket.timeout:
        pass
    recv_sock.close()
    return list(devices.values())


def discover(sku: str = DEVICE_SKU, timeout: float = 5.0) -> str | None:
    """Scan LAN; return IP of first device matching sku, or None."""
    recv_sock = _open_recv_sock(timeout)
    if recv_sock is None:
        print(
            f"  Cannot bind port {_RECV_PORT} — Govee Desktop is likely using it.\n"
            f"  Close Govee Desktop or set DEVICE_IP manually."
        )
        return None
    _broadcast_scan()
    found_ip = None
    try:
        while True:
            data, addr = recv_sock.recvfrom(4096)
            try:
                msg = json.loads(data.decode())
                d = msg.get("msg", {}).get("data", {})
                if d.get("sku") == sku:
                    found_ip = d.get("ip", addr[0])
                    break
            except json.JSONDecodeError:
                pass
    except socket.timeout:
        pass
    recv_sock.close()
    return found_ip


# --- Basic commands ---

def turn_on(ip: str):
    _send(ip, "turn", {"value": 1})


def turn_off(ip: str):
    _send(ip, "turn", {"value": 0})


def set_brightness(ip: str, pct: int):
    _send(ip, "brightness", {"value": pct})


def set_color(ip: str, r: int, g: int, b: int):
    _send(ip, "colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})


def get_status(ip: str, timeout: float = 2.0) -> dict | None:
    """Request and return device status dict."""
    _send(ip, "devStatus", {})
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", _RECV_PORT))
    sock.settimeout(timeout)
    try:
        data, _ = sock.recvfrom(1024)
        return json.loads(data.decode())
    except socket.timeout:
        return None
    finally:
        sock.close()


# --- ptReal / Graffiti per-segment control ---

def _a3_packet(index: int, is_last: bool, chunk: bytes) -> str:
    raw = bytes([0xa3, 0xff if is_last else index]) + chunk
    raw = raw.ljust(19, b'\x00')
    return base64.b64encode(raw + bytes([_xor(raw)])).decode()


_GRAFFITI_MODE_PACKET = "MwUKIAMAAAAAAAAAAAAAAAAAAB8="


def _scene_terminator(scene_code: int) -> str:
    lo, hi = scene_code & 0xff, (scene_code >> 8) & 0xff
    raw = bytes([0x33, 0x05, 0x04, lo, hi]) + b'\x00' * 14
    return base64.b64encode(raw + bytes([_xor(raw)])).decode()


def _build_scene_packets(scence_param: bytes, final_packet: str) -> list:
    num_pkts = max(1, -(-(3 + len(scence_param)) // 17))
    full = bytes([0x01, num_pkts, 0x02]) + scence_param
    packets = [
        _a3_packet(i, i == num_pkts - 1, full[i * 17:(i + 1) * 17])
        for i in range(num_pkts)
    ]
    packets.append(final_packet)
    return packets


def play_scene(ip: str, scence_param_b64: str, scene_code: int):
    """Send a predefined Govee scene by its base64 scenceParam and sceneCode."""
    packets = _build_scene_packets(
        base64.b64decode(scence_param_b64),
        _scene_terminator(scene_code),
    )
    _send(ip, "ptReal", {"command": packets})


def _build_graffiti(segments: list, anim_dir: int = 0x00) -> list:
    scence_param = bytearray([0x03, anim_dir, 0x00, 0x00, 0x00, 0x00, 0x00, len(segments)])
    for (r, g, b), pixel_ids in segments:
        scence_param += bytes([len(pixel_ids), r, g, b] + pixel_ids)
    return _build_scene_packets(scence_param, _GRAFFITI_MODE_PACKET)


def set_segments(ip: str, pixel_colors: list):
    """
    Set per-pixel colors via ptReal graffiti mode.
    pixel_colors: list of (R, G, B) tuples. Consecutive same-color pixels are merged.
    """
    segments = []
    for i, color in enumerate(pixel_colors):
        if segments and segments[-1][0] == color:
            segments[-1][1].append(i)
        else:
            segments.append([color, [i]])
    packets = _build_graffiti([(color, pxids) for color, pxids in segments])
    _send(ip, "ptReal", {"command": packets})


def animate_chase_framebased(ip: str, num_pixels: int = 14, step_interval: float = 0.2):
    """Frame-by-frame ptReal chase animation. Ctrl+C to stop."""
    HEAD  = (255, 96, 0)
    TAIL1 = (153, 51, 0)
    TAIL2 = ( 51, 15, 0)
    BG    = (  0,  0, 0)

    def _frame(pos):
        h, t1, t2 = pos % num_pixels, (pos - 1) % num_pixels, (pos - 2) % num_pixels
        bg = sorted(set(range(num_pixels)) - {h, t1, t2})
        segs = [(HEAD, [h]), (TAIL1, [t1]), (TAIL2, [t2])]
        if bg:
            segs.append((BG, bg))
        return segs

    print(f"chase ({num_pixels}px, {step_interval}s/step) — Ctrl+C to stop")
    step = 0
    try:
        while True:
            packets = _build_graffiti(_frame(step))
            _send(ip, "ptReal", {"command": packets if step == 0 else packets[:-1]})
            step += 1
            time.sleep(step_interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def animate_chase_device(ip: str, num_pixels: int = 14, anim_dir: int = 0x09):
    """Single ptReal command — device animates internally.
    anim_dir: 0x02=Cycle, 0x09=Up, 0x0a=Down
    """
    HEAD  = (255, 96, 0)
    TAIL1 = (153, 51, 0)
    TAIL2 = ( 51, 15, 0)
    BG    = (  0,  0, 0)
    segments = [(HEAD, [0]), (TAIL1, [1]), (TAIL2, [2]), (BG, list(range(3, num_pixels)))]
    scence_param = bytes([0x03, anim_dir, 0x00, 0x00, 0x00, 0x00, 0x00, len(segments)])
    for (r, g, b), pixel_ids in segments:
        scence_param += bytes([len(pixel_ids), r, g, b] + pixel_ids)
    packets = _build_scene_packets(scence_param, _GRAFFITI_MODE_PACKET)
    _send(ip, "ptReal", {"command": packets})
