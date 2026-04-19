"""
ui.py - Lumovee

Cross-platform Qt6 app (Windows + KDE) for routing Hyperion/HyperHDR to a Govee strip.
Discovers all devices on the LAN, lets you select one, and routes UDP Raw frames to it.

Requirements:
    pip install PySide6

Usage:
    python src/ui.py
"""

import sys
import os
import time
import socket
import math

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QLabel, QSlider, QSizePolicy,
    QAbstractButton, QSystemTrayIcon, QMenu, QSpinBox, QToolButton,
    QScrollArea, QFrame, QGridLayout, QLineEdit,
    QStackedWidget, QButtonGroup,
)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction, QPen, QPolygonF, QTransform, QPalette
from PySide6.QtCore import Qt, QThread, Signal, Slot, QSettings, QSize, QRectF, QPointF, Property, QPropertyAnimation, QEasingCurve

from govee import (
    discover_all, turn_on, turn_off, set_brightness, get_status,
    razer_start, razer_stop, set_segments_razer, NUM_SEGMENTS,
)

LISTEN_PORT = 5568
APP_NAME    = "Lumovee"


# ── Autostart helpers ─────────────────────────────────────────────────────────

def _autostart_get() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except OSError:
            return False
    else:
        return os.path.exists(_kde_autostart_path())


def _autostart_set(enabled: bool):
    if sys.platform == "win32":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enabled:
            cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    else:
        path = _kde_autostart_path()
        if enabled:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(f"[Desktop Entry]\n"
                        f"Type=Application\n"
                        f"Name=Lumovee\n"
                        f'Exec="{sys.executable}" "{os.path.abspath(__file__)}"\n'
                        f"Hidden=false\n"
                        f"X-GNOME-Autostart-enabled=true\n")
        elif os.path.exists(path):
            os.remove(path)


def _kde_autostart_path() -> str:
    return os.path.expanduser(f"~/.config/autostart/{APP_NAME}.desktop")


# ── Icons ─────────────────────────────────────────────────────────────────────

# Tray status colours: (L body, bulb)
_TRAY_COLORS = {
    "idle":     ("#888888", "#aaaaaa"),
    "scanning": ("#CC7700", "#FFAA00"),
    "routing":  ("#22AA22", "#66FF66"),
    "error":    ("#CC2222", "#FF6666"),
}


def _draw_logo(p: QPainter, size: int, l_color: QColor, bulb_color: QColor):
    """
    Draw the Lumovee logo: an L with a dot on top as a light bulb.

    Layout (proportional):
      • Bulb  — filled circle sitting at the top of the vertical bar
      • Vert  — vertical bar of the L
      • Horiz — horizontal bar of the L along the bottom
    """
    m  = size * 0.14          # outer margin
    sw = size * 0.22          # stroke width
    br = sw * 0.72            # bulb radius (slightly wider than stroke)

    # Centres and extents
    bar_x  = m                          # left edge of vertical bar
    bar_cx = bar_x + sw / 2             # horizontal centre of vertical bar
    bulb_cy = m + br                    # bulb centre y

    bar_top    = bulb_cy + br * 1.1     # vertical bar starts just below bulb
    bar_bottom = size - m - sw          # aligns with top of horizontal bar
    bar_h      = bar_bottom - bar_top

    horiz_y = size - m - sw
    horiz_w = size - m * 2

    rr = sw * 0.35   # rounding radius for bars

    p.setPen(Qt.PenStyle.NoPen)

    # Vertical bar
    p.setBrush(l_color)
    p.drawRoundedRect(bar_x, bar_top, sw, bar_h + sw, rr, rr)

    # Horizontal bar
    p.drawRoundedRect(bar_x, horiz_y, horiz_w, sw, rr, rr)

    # Bulb
    p.setBrush(bulb_color)
    p.drawEllipse(bar_cx - br, bulb_cy - br, br * 2, br * 2)


def _make_window_icon() -> QIcon:
    """Multi-resolution window/taskbar icon: dark background + Lumovee logo."""
    icon = QIcon()
    for size in (16, 32, 48, 64):
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dark rounded background
        p.setBrush(QColor("#1E1E2E"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)

        _draw_logo(p, size, QColor("#FFFFFF"), QColor("#FFFFFF"))
        p.end()
        icon.addPixmap(px)
    return icon


def _make_tray_icon(status: str = "idle") -> QIcon:
    """22×22 tray icon using the Lumovee logo, coloured by status."""
    l_hex, bulb_hex = _TRAY_COLORS.get(status, _TRAY_COLORS["idle"])
    px = QPixmap(22, 22)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_logo(p, 22, QColor(l_hex), QColor(bulb_hex))
    p.end()
    return QIcon(px)


def _make_power_icon(on: bool | None = None, size: int = 16, color: QColor | None = None) -> QIcon:
    """Power button symbol: arc with gap at top + vertical line.
    When color is given it overrides on-based colouring. When both are None, uses palette WindowText."""
    if color is None:
        if on is True:
            color = QColor("#44BB44")
        elif on is False:
            color = QColor("#BB4444")
        else:
            color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = size / 2, size / 2
    r  = size * 0.33
    lw = max(1.5, size * 0.11)

    pen = QPen(color, lw, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Arc with ~60° gap at 12 o'clock: start at 60°, span -300° (clockwise)
    p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2).toAlignedRect(),
              60 * 16, -300 * 16)

    # Vertical line from inside circle up through the gap
    p.drawLine(int(cx), int(cy - r * 0.2), int(cx), int(cy - r - size * 0.08))

    p.end()
    return QIcon(px)


def _make_sun_icon(size: int = 16, color: QColor | None = None) -> QIcon:
    """Sun symbol: small filled circle + 8 short rays.
    Color defaults to the current window-text palette color (adapts to dark/light mode)."""
    if color is None:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPalette
        color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = size / 2, size / 2
    lw = max(1.0, size * 0.1)
    pen = QPen(color, lw, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)

    r_core = size * 0.20
    p.drawEllipse(QRectF(cx - r_core, cy - r_core, r_core * 2, r_core * 2))

    r0, r1 = size * 0.30, size * 0.44
    for i in range(8):
        a = math.radians(i * 45)
        p.drawLine(
            QPointF(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
            QPointF(cx + r1 * math.cos(a), cy + r1 * math.sin(a)),
        )

    p.end()
    return QIcon(px)


def _make_bulb_icon(on: bool = False, color: QColor | None = None, size: int = 20) -> QIcon:
    """Light bulb: filled + colored when on, hollow dimmed outline when off."""
    from PySide6.QtGui import QPalette
    cx, cy = size / 2, size * 0.38
    r  = size * 0.29
    lw = max(1.0, size * 0.085)

    if on and color:
        line_color = color.darker(150)
        fill: QColor | None = color
    else:
        base = QApplication.palette().color(QPalette.ColorRole.WindowText)
        line_color = QColor(base.red(), base.green(), base.blue(), 80)
        fill = None

    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(line_color, lw, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)

    # Glass circle
    p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    # Screw base: two narrowing horizontal lines below the glass
    p.setBrush(Qt.BrushStyle.NoBrush)
    y1 = cy + r + lw * 0.8
    y2 = y1 + lw * 1.6
    p.drawLine(QPointF(cx - r * 0.65, y1), QPointF(cx + r * 0.65, y1))
    p.drawLine(QPointF(cx - r * 0.42, y2), QPointF(cx + r * 0.42, y2))

    p.end()
    return QIcon(px)


def _make_pencil_icon(size: int = 12) -> QIcon:
    """Pencil shape (body + triangular tip), rotated 45°, palette-coloured."""
    from PySide6.QtGui import QPalette
    color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(color, 0.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(color)

    # Pencil drawn tip-down, then rotated 45° so it points bottom-right
    w        = size * 0.30
    body_top = -size * 0.42
    body_bot =  size * 0.18
    tip_bot  =  size * 0.44

    poly = QPolygonF([
        QPointF(-w / 2, body_top),
        QPointF( w / 2, body_top),
        QPointF( w / 2, body_bot),
        QPointF(0,      tip_bot),
        QPointF(-w / 2, body_bot),
    ])

    t = QTransform()
    t.translate(size / 2, size / 2)
    t.rotate(45)
    p.setTransform(t)
    p.drawPolygon(poly)
    p.end()
    return QIcon(px)


def _make_devices_icon(size: int = 22) -> QIcon:
    """2×2 grid of rounded squares — represents multiple devices."""
    from PySide6.QtGui import QPalette
    color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    m = size * 0.12
    g = size * 0.10
    s = (size - 2 * m - g) / 2
    rr = s * 0.25
    for row in range(2):
        for col in range(2):
            x = m + col * (s + g)
            y = m + row * (s + g)
            p.drawRoundedRect(QRectF(x, y, s, s), rr, rr)
    p.end()
    return QIcon(px)


def _make_scan_icon(size: int = 22) -> QIcon:
    """Circular refresh arrow — represents scanning / rediscovery."""
    color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = size / 2.0, size / 2.0
    r  = size * 0.36
    lw = max(1.5, size * 0.12)
    pen = QPen(color, lw, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Arc: ~300° starting from the top-right (clockwise gap at top-left)
    p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 120 * 16, -300 * 16)

    # Arrow head at the end of the arc (around 120° + gap start)
    tip_a  = math.radians(120)
    tip    = QPointF(cx + r * math.cos(tip_a), cy - r * math.sin(tip_a))
    # Two short lines forming a V pointing along the arc tangent
    tang_a = tip_a + math.pi / 2          # tangent direction at tip
    hs     = size * 0.18                  # half-arrow size
    left   = QPointF(tip.x() + hs * math.cos(tang_a + 0.6),
                     tip.y() - hs * math.sin(tang_a + 0.6))
    right  = QPointF(tip.x() + hs * math.cos(tang_a - 0.6),
                     tip.y() - hs * math.sin(tang_a - 0.6))
    p.drawLine(tip, left)
    p.drawLine(tip, right)

    p.end()
    return QIcon(px)


def _make_settings_icon(size: int = 22) -> QIcon:
    """Gear / cog icon — represents settings."""
    from PySide6.QtGui import QPalette
    color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)

    cx, cy = size / 2.0, size / 2.0
    r_outer = size * 0.42
    r_inner = size * 0.26
    r_hub   = size * 0.15
    teeth   = 8

    # Build gear outline as a polygon: alternate between outer and inner radius
    pts = []
    for i in range(teeth * 2):
        a = math.radians(i * 180 / teeth - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
    p.drawPolygon(QPolygonF(pts))

    # Punch out centre with background color
    p.setBrush(QApplication.palette().color(QPalette.ColorRole.Window))
    p.drawEllipse(QRectF(cx - r_hub, cy - r_hub, r_hub * 2, r_hub * 2))

    p.end()
    return QIcon(px)


def _make_dreamview_icon(size: int = 22) -> QIcon:
    """Filled right-pointing triangle — represents routing/play."""
    from PySide6.QtGui import QPalette
    color = QApplication.palette().color(QPalette.ColorRole.WindowText)
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    m = size * 0.18
    poly = QPolygonF([
        QPointF(m,          m),
        QPointF(size - m,   size / 2),
        QPointF(m,          size - m),
    ])
    p.drawPolygon(poly)
    p.end()
    return QIcon(px)


# ── Toggle switch ─────────────────────────────────────────────────────────────

class ToggleSwitch(QAbstractButton):
    """Animated iOS-style toggle switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self._offset: float = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

    # Qt property so QPropertyAnimation can drive it
    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, v: float):
        self._offset = v
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def setChecked(self, checked: bool):
        """Snap to position immediately (no animation) for programmatic sets."""
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def nextCheckState(self):
        """Animate on user click."""
        super().nextCheckState()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if self.isChecked() else 0.0)
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 3

        track = (QApplication.palette().color(QPalette.ColorRole.Highlight)
                 if self.isChecked() else
                 QApplication.palette().color(QPalette.ColorRole.Mid))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        thumb_x = pad + self._offset * (w - h)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(thumb_x, pad, h - pad * 2, h - pad * 2))
        p.end()

    def sizeHint(self):
        return QSize(44, 24)


# ── Workers ───────────────────────────────────────────────────────────────────

class DiscoveryWorker(QThread):
    discovered = Signal(list)   # list[{"sku": str, "ip": str}]

    def run(self):
        self.discovered.emit(discover_all())


class RouterWorker(QThread):
    frame_update = Signal(int, float)   # (total_frames, fps)
    error        = Signal(str)

    def __init__(self, ip: str, port: int):
        super().__init__()
        self._ip = ip
        self._port = port
        self._running = False

    @Slot()
    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        try:
            turn_on(self._ip)
            razer_start(self._ip)
        except Exception as e:
            self.error.emit(f"Start failed: {e}")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        sock.bind(("0.0.0.0", self._port))
        sock.settimeout(0.1)

        frames = 0
        ts_window: list[float] = []

        try:
            while self._running:
                # Block until at least one frame arrives
                try:
                    data, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    # OS receive buffer overflow — skip and keep going
                    continue

                # Drain any queued frames so we always forward the freshest one
                sock.setblocking(False)
                try:
                    while True:
                        data, _ = sock.recvfrom(65535)
                except (BlockingIOError, OSError):
                    pass
                finally:
                    sock.settimeout(0.1)

                if not data or len(data) % 3 != 0:
                    continue
                leds = [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]
                if len(leds) != NUM_SEGMENTS:
                    continue

                try:
                    set_segments_razer(self._ip, leds)
                except Exception as e:
                    self.error.emit(str(e))
                    break

                frames += 1
                now = time.monotonic()
                ts_window.append(now)
                ts_window = [t for t in ts_window if now - t < 1.0]
                if frames % 30 == 0:
                    if len(ts_window) >= 2:
                        fps = (len(ts_window) - 1) / (ts_window[-1] - ts_window[0])
                    else:
                        fps = 0.0
                    self.frame_update.emit(frames, fps)
        finally:
            sock.close()
            try:
                razer_stop(self._ip)
            except Exception:
                pass


class StatusFetcher(QThread):
    """Fetches devStatus for each IP sequentially and emits one signal per device."""
    status_ready = Signal(str, dict)   # (ip, data-dict from devStatus response)

    def __init__(self, ips: list[str]):
        super().__init__()
        self._ips = ips

    def run(self):
        for ip in self._ips:
            try:
                result = get_status(ip)
                if result:
                    data = result.get("msg", {}).get("data", {})
                    self.status_ready.emit(ip, data)
            except Exception:
                pass


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lumovee")
        self.setFixedSize(460, 320)
        self.setWindowIcon(_make_window_icon())

        self._worker: RouterWorker | None = None
        self._discovery: DiscoveryWorker | None = None
        self._status_fetcher: StatusFetcher | None = None
        self._devices: list[dict] = []
        self._quitting = False
        self._auto_route_done = False
        self._scanning = False           # True while discovery + combo rebuild is in flight
        self._scan_routing_ip: str | None = None  # routing IP captured before combo clear
        self._settings = QSettings(APP_NAME, APP_NAME)

        # Per-card widget refs (keyed by IP), populated by _make_device_card
        self._card_bulbs:        dict[str, QLabel]        = {}
        self._card_sliders:      dict[str, QSlider]       = {}
        self._card_bright_labels:dict[str, QLabel]        = {}
        self._card_colors:       dict[str, QColor]        = {}
        self._card_power_toggles:dict[str, ToggleSwitch]  = {}

        # ── Central widget ──
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Sidebar ──
        sidebar = QWidget()
        sidebar.setFixedWidth(48)
        sidebar.setObjectName("sidebar")
        sidebar.setStyleSheet("""
            QWidget#sidebar {
                border-right: 1px solid palette(mid);
            }
            QToolButton {
                border-radius: 6px;
                border: none;
                background: transparent;
            }
            QToolButton:checked {
                background-color: palette(highlight);
            }
            QToolButton:hover:!checked {
                background-color: palette(mid);
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(4, 8, 4, 8)
        sidebar_layout.setSpacing(4)

        self._stack = QStackedWidget()

        def _nav_btn(icon: QIcon, tooltip: str, index: int) -> QToolButton:
            btn = QToolButton()
            btn.setIcon(icon)
            btn.setIconSize(QSize(22, 22))
            btn.setFixedSize(40, 40)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda: self._stack.setCurrentIndex(index))
            return btn

        devices_btn   = _nav_btn(_make_devices_icon(),   "Devices",   0)
        dreamview_btn = _nav_btn(_make_dreamview_icon(), "DreamView", 1)
        settings_btn  = _nav_btn(_make_settings_icon(),  "Settings",  2)

        self._nav_group = QButtonGroup(root)
        self._nav_group.addButton(devices_btn)
        self._nav_group.addButton(dreamview_btn)
        self._nav_group.addButton(settings_btn)
        self._nav_group.setExclusive(True)
        devices_btn.setChecked(True)

        sidebar_layout.addWidget(devices_btn)
        sidebar_layout.addWidget(dreamview_btn)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(settings_btn)

        outer.addWidget(sidebar)
        outer.addWidget(self._stack)

        # ── Tab 1: Devices ─────────────────────────────────────────────────────
        device_tab = QWidget()
        device_layout = QVBoxLayout(device_tab)
        device_layout.setSpacing(8)
        device_layout.setContentsMargins(12, 12, 12, 12)

        # Scan row
        scan_row = QHBoxLayout()
        self._scan_btn = QToolButton()
        self._scan_btn.setIcon(_make_scan_icon())
        self._scan_btn.setIconSize(QSize(22, 22))
        self._scan_btn.setFixedSize(36, 36)
        self._scan_btn.setToolTip("Scan for devices")
        self._scan_btn.clicked.connect(self._scan)
        scan_row.addWidget(self._scan_btn)
        self._scan_status_label = QLabel("Press scan to discover devices")
        scan_row.addWidget(self._scan_status_label)
        scan_row.addStretch()
        device_layout.addLayout(scan_row)

        # Scroll area for device boxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        scroll.setFrameShadow(QFrame.Shadow.Sunken)
        self._devices_container = QWidget()
        self._devices_layout = QGridLayout(self._devices_container)
        self._devices_layout.setSpacing(10)
        self._devices_layout.setContentsMargins(10, 10, 10, 10)
        self._devices_layout.setColumnStretch(0, 1)
        self._devices_layout.setColumnStretch(1, 1)
        scroll.setWidget(self._devices_container)
        device_layout.addWidget(scroll)

        self._stack.addWidget(device_tab)   # index 0

        # ── Tab 2: DreamView ───────────────────────────────────────────────────
        routing_tab = QWidget()
        routing_layout = QVBoxLayout(routing_tab)
        routing_layout.setSpacing(10)
        routing_layout.setContentsMargins(16, 16, 16, 16)

        # Route toggle + status row
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._route_toggle = ToggleSwitch()
        self._route_toggle.setEnabled(False)
        self._route_toggle.setToolTip("Start / stop DreamView routing")
        self._route_toggle.toggled.connect(self._on_route_toggled)
        status_row.addWidget(self._route_toggle)
        self._dot = QLabel("●")
        self._dot.setFixedWidth(18)
        self._status_label = QLabel("Idle")
        status_row.addWidget(self._dot)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        self._fps_label = QLabel("")
        self._fps_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_row.addWidget(self._fps_label)
        routing_layout.addLayout(status_row)

        # Device selection row
        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Device"))
        self._combo = QComboBox()
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo.setStyleSheet("""
            QComboBox {
                border: 1px solid palette(mid);
                border-radius: 6px;
                padding: 4px 8px 4px 10px;
                background: palette(base);
                color: palette(text);
                min-height: 26px;
            }
            QComboBox:hover:!disabled { border-color: palette(highlight); }
            QComboBox:disabled        { color: palette(mid); }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 26px;
                border: none;
                border-left: 1px solid palette(mid);
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid palette(mid);
                border-radius: 4px;
                background: palette(base);
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
                padding: 2px;
                outline: none;
            }
            QComboBox QAbstractItemView::item { padding: 4px 8px; min-height: 24px; }
        """)
        self._combo.currentIndexChanged.connect(self._on_device_changed)
        dev_row.addWidget(self._combo)
        routing_layout.addLayout(dev_row)

        # Port row
        _port_tip = (
            "The UDP port Lumovee listens on for incoming UDP Raw frames.\n"
            "Set this same port as the output port in Hyperion or HyperHDR."
        )
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("UDP Raw port"))
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(self._settings.value("listen_port", LISTEN_PORT, type=int))
        self._port_spin.setFixedWidth(80)
        self._port_spin.valueChanged.connect(lambda v: self._settings.setValue("listen_port", v))
        port_row.addWidget(self._port_spin)
        _port_hint = QToolButton()
        _port_hint.setText("?")
        _port_hint.setToolTip(_port_tip)
        _port_hint.setCursor(Qt.CursorShape.WhatsThisCursor)
        _port_hint.setStyleSheet(
            "QToolButton { border: 1px solid gray; border-radius: 8px;"
            " width: 16px; height: 16px; color: gray; font-size: 10px; }"
        )
        _port_hint.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        port_row.addWidget(_port_hint)
        port_row.addStretch()
        routing_layout.addLayout(port_row)

        routing_layout.addStretch()
        self._stack.addWidget(routing_tab)  # index 1

        # ── Tab 3: Settings ────────────────────────────────────────────────────
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setSpacing(16)
        settings_layout.setContentsMargins(16, 16, 16, 16)

        # Autostart toggle
        autostart_row = QHBoxLayout()
        self._autostart_cb = ToggleSwitch()
        self._autostart_cb.setChecked(_autostart_get())
        self._autostart_cb.toggled.connect(_autostart_set)
        autostart_row.addWidget(self._autostart_cb)
        autostart_row.addWidget(QLabel("Start automatically with system"))
        autostart_row.addStretch()
        settings_layout.addLayout(autostart_row)

        settings_layout.addStretch()
        self._stack.addWidget(settings_tab)  # index 2

        # ── Tray icon ──
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon("idle"))
        self._tray.setToolTip("Lumovee")

        tray_menu = QMenu()
        self._tray_show_action = QAction("Show", self)
        self._tray_show_action.triggered.connect(self._show_window)
        tray_menu.addAction(self._tray_show_action)
        tray_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self._set_status("idle")
        self._scan()    # auto-scan on launch

    # ── Tray ──

    def _show_window(self):
        self.showNormal()
        self.activateWindow()
        self._tray_show_action.setText("Hide")

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
                self._tray_show_action.setText("Show")
            else:
                self._show_window()

    def _quit(self):
        self._quitting = True
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        QApplication.quit()

    # ── Status helper ──

    def _set_status(self, state: str, msg: str = ""):
        dot_color = {"idle": "gray", "scanning": "orange", "routing": "lime", "error": "red"}
        label     = {"idle": "Idle", "scanning": "Scanning…", "routing": "Routing", "error": f"Error: {msg}"}
        self._dot.setStyleSheet(f"color: {dot_color.get(state, 'gray')};")
        self._status_label.setText(label.get(state, msg))
        if state != "routing":
            self._fps_label.setText("")
        self._tray.setIcon(_make_tray_icon(state))
        self._tray.setToolTip(f"Lumovee – {label.get(state, msg)}")

    def _current_ip(self) -> str | None:
        idx = self._combo.currentIndex()
        return self._devices[idx]["ip"] if 0 <= idx < len(self._devices) else None

    # ── Device boxes ──

    _CARD_COLS = 2
    _CARD_H    = 140

    def _build_device_boxes(self):
        """Rebuild device cards in a 2-column grid (row-major order)."""
        self._card_bulbs.clear()
        self._card_sliders.clear()
        self._card_bright_labels.clear()
        self._card_power_toggles.clear()
        for r in range(self._devices_layout.rowCount()):
            self._devices_layout.setRowStretch(r, 0)
        while self._devices_layout.count():
            item = self._devices_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        sorted_devices = sorted(
            self._devices,
            key=lambda d: self._settings.value(f"device_name_{d['ip']}", d["sku"]).lower(),
        )
        for i, device in enumerate(sorted_devices):
            row, col = divmod(i, self._CARD_COLS)
            self._devices_layout.addWidget(self._make_device_card(device), row, col)

        next_row = (len(self._devices) + self._CARD_COLS - 1) // self._CARD_COLS
        self._devices_layout.setRowStretch(next_row, 1)

    def _make_device_card(self, device: dict) -> QFrame:
        ip  = device["ip"]
        sku = device["sku"]
        custom_name = self._settings.value(f"device_name_{ip}", sku)

        icon_size = QSize(16, 16)

        # ── Card shell ──
        from PySide6.QtGui import QPalette as _P
        _pal = QApplication.palette()
        _bg  = _pal.color(_P.ColorRole.Button).name()
        _bdr = _pal.color(_P.ColorRole.Mid).name()

        box = QFrame()
        box.setFixedHeight(self._CARD_H)
        box.setObjectName("device_card")
        box.setStyleSheet(f"""
            QFrame#device_card {{
                background-color: {_bg};
                border: 1px solid {_bdr};
                border-radius: 8px;
            }}
            QFrame#device_card > QWidget {{
                background: transparent;
                border: none;
            }}
        """)
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(0)
        box_layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ──
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setSpacing(2)
        header_layout.setContentsMargins(10, 8, 8, 6)

        # Name row: label + pencil button (swaps to QLineEdit while editing) + bulb
        name_row = QHBoxLayout()
        name_row.setSpacing(4)

        name_label = QLabel(custom_name)
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_row.addWidget(name_label)

        name_edit = QLineEdit(custom_name)
        name_edit.hide()
        name_row.addWidget(name_edit)

        pencil_btn = QPushButton()
        pencil_btn.setIcon(_make_pencil_icon(12))
        pencil_btn.setIconSize(QSize(12, 12))
        pencil_btn.setFixedSize(20, 20)
        pencil_btn.setFlat(True)
        pencil_btn.setToolTip("Rename device")
        name_row.addWidget(pencil_btn)
        name_row.addStretch()

        # Bulb icon — hollow until status arrives
        bulb_lbl = QLabel()
        bulb_lbl.setPixmap(_make_bulb_icon(on=False, size=20).pixmap(20, 20))
        bulb_lbl.setToolTip("Device power state / colour")
        name_row.addWidget(bulb_lbl)
        self._card_bulbs[ip] = bulb_lbl

        header_layout.addLayout(name_row)

        ip_label = QLabel(f"{sku}  ·  {ip}")
        ip_font = ip_label.font()
        ip_font.setPointSize(ip_font.pointSize() - 1)
        ip_label.setFont(ip_font)
        ip_label.setStyleSheet("color: gray;")
        header_layout.addWidget(ip_label)

        box_layout.addWidget(header)

        # ── Edit/confirm logic ──
        def _start_edit():
            name_label.hide()
            pencil_btn.hide()
            name_edit.setText(name_label.text())
            name_edit.show()
            name_edit.setFocus()
            name_edit.selectAll()

        def _finish_edit():
            if not name_edit.isVisible():
                return
            new_name = name_edit.text().strip() or sku
            self._settings.setValue(f"device_name_{ip}", new_name)
            name_label.setText(new_name)
            name_edit.hide()
            name_label.show()
            pencil_btn.show()
            # Keep DreamView combo in sync
            for idx in range(self._combo.count()):
                if self._combo.itemData(idx) == ip:
                    self._combo.setItemText(idx, f"{new_name}  –  {ip}")
                    break

        pencil_btn.clicked.connect(_start_edit)
        name_edit.returnPressed.connect(_finish_edit)
        name_edit.editingFinished.connect(_finish_edit)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        box_layout.addWidget(sep)

        # ── Controls ──
        controls = QWidget()
        ctrl_layout = QVBoxLayout(controls)
        ctrl_layout.setSpacing(6)
        ctrl_layout.setContentsMargins(10, 8, 10, 8)

        def _on_power_toggled(checked: bool):
            if checked:
                turn_on(ip)
                c = self._card_colors.get(ip, QColor(255, 255, 255))
                self._card_bulbs[ip].setPixmap(
                    _make_bulb_icon(on=True, color=c, size=20).pixmap(20, 20))
            else:
                turn_off(ip)
                self._card_bulbs[ip].setPixmap(
                    _make_bulb_icon(on=False, size=20).pixmap(20, 20))

        power_row = QHBoxLayout()
        power_icon_lbl = QLabel()
        power_icon_lbl.setPixmap(_make_power_icon().pixmap(icon_size))
        power_icon_lbl.setToolTip("Power")
        power_row.addWidget(power_icon_lbl)
        power_toggle = ToggleSwitch()
        power_toggle.setToolTip("Turn On / Off")
        power_toggle.toggled.connect(_on_power_toggled)
        power_row.addWidget(power_toggle)
        power_row.addStretch()
        ctrl_layout.addLayout(power_row)
        self._card_power_toggles[ip] = power_toggle

        bright_row = QHBoxLayout()
        sun_label = QLabel()
        sun_label.setPixmap(_make_sun_icon(16).pixmap(16, 16))
        sun_label.setToolTip("Brightness")
        bright_row.addWidget(sun_label)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(1, 100)
        saved_bright = self._settings.value(f"brightness_{ip}", 100, type=int)
        slider.setValue(saved_bright)
        val_label = QLabel(f"{saved_bright}%")
        val_label.setFixedWidth(38)
        slider.valueChanged.connect(
            lambda v, _ip=ip, _lbl=val_label: self._on_device_brightness(v, _ip, _lbl)
        )
        bright_row.addWidget(slider)
        bright_row.addWidget(val_label)
        ctrl_layout.addLayout(bright_row)

        self._card_sliders[ip]       = slider
        self._card_bright_labels[ip] = val_label

        box_layout.addWidget(controls)
        return box

    def _on_device_brightness(self, value: int, ip: str, val_label: QLabel):
        val_label.setText(f"{value}%")
        self._settings.setValue(f"brightness_{ip}", value)
        set_brightness(ip, value)

    # ── Scan ──

    def _scan(self):
        if self._discovery and self._discovery.isRunning():
            return
        routing_active = bool(self._worker and self._worker.isRunning())
        self._scanning = True
        self._scan_routing_ip = self._current_ip()   # capture before combo is cleared
        self._devices = []
        self._scan_btn.setEnabled(False)
        self._scan_status_label.setText("Scanning…")
        if not routing_active:
            self._route_toggle.setEnabled(False)
            self._set_status("scanning")
        self._discovery = DiscoveryWorker()
        self._discovery.discovered.connect(self._on_discovered)
        self._discovery.start()

    @Slot(list)
    def _on_discovered(self, devices: list):
        routing_active   = bool(self._worker and self._worker.isRunning())
        routing_ip       = self._scan_routing_ip   # may be None if not routing

        self._scan_btn.setEnabled(True)
        self._devices = devices

        # _scanning is still True here — combo changes won't touch the worker
        self._combo.clear()
        self._build_device_boxes()
        for d in devices:
            name = self._settings.value(f"device_name_{d['ip']}", d['sku'])
            self._combo.addItem(f"{name}  –  {d['ip']}", d['ip'])

        if devices:
            self._scan_status_label.setText(
                f"Found {len(devices)} device{'s' if len(devices) != 1 else ''}"
            )
            if routing_active and routing_ip:
                # Restore routing device's combo index; keep routing status as-is
                for i, d in enumerate(devices):
                    if d["ip"] == routing_ip:
                        self._combo.setCurrentIndex(i)
                        break
            else:
                self._set_status("idle")
                self._route_toggle.setEnabled(True)
                last_ip = self._settings.value("last_device_ip", "")
                for i, d in enumerate(devices):
                    if d["ip"] == last_ip:
                        self._combo.setCurrentIndex(i)
                        break

            # Safe to clear flag now — combo is fully settled
            self._scanning = False

            # Fetch live status for each device to populate bulbs + sliders
            self._status_fetcher = StatusFetcher([d["ip"] for d in devices])
            self._status_fetcher.status_ready.connect(self._on_status_ready)
            self._status_fetcher.start()

            # Auto-start routing on launch (once only, never while already routing)
            if not routing_active and self._settings.value("routing_active", False, type=bool) and not self._auto_route_done:
                self._auto_route_done = True
                self._start()
        else:
            self._scanning = False
            if not routing_active:
                self._set_status("error", "No devices found")
            self._scan_status_label.setText("No devices found")

    @Slot(str, dict)
    def _on_status_ready(self, ip: str, data: dict):
        """Update card bulb and brightness slider from a live devStatus response."""
        on  = bool(data.get("onOff", 0))
        col = data.get("color", {})
        r, g, b = col.get("r", 255), col.get("g", 255), col.get("b", 255)

        # Black while on = Dreamview/Razer mode active, real color not reported
        if on and r + g + b < 15:
            color = QColor(255, 200, 80)   # warm white placeholder
        else:
            color = QColor(r, g, b)

        if on:
            self._card_colors[ip] = color

        bulb = self._card_bulbs.get(ip)
        if bulb:
            bulb.setPixmap(
                _make_bulb_icon(on=on, color=color if on else None, size=20).pixmap(20, 20)
            )

        toggle = self._card_power_toggles.get(ip)
        if toggle:
            toggle.blockSignals(True)
            toggle.setChecked(on)
            toggle.blockSignals(False)

        brightness = data.get("brightness")
        if brightness is not None:
            slider = self._card_sliders.get(ip)
            lbl    = self._card_bright_labels.get(ip)
            if slider:
                slider.blockSignals(True)
                slider.setValue(brightness)
                slider.blockSignals(False)
            if lbl:
                lbl.setText(f"{brightness}%")

    # ── Device change while routing ──

    def _on_device_changed(self, _index: int):
        if self._scanning:
            return   # combo is being rebuilt — ignore
        if self._worker and self._worker.isRunning():
            self._stop()

    # ── Start / Stop ──

    def _on_route_toggled(self, checked: bool):
        if checked:
            self._start()
        else:
            self._stop()

    def _start(self):
        ip = self._current_ip()
        if not ip:
            self._route_toggle.blockSignals(True)
            self._route_toggle.setChecked(False)
            self._route_toggle.blockSignals(False)
            return
        self._settings.setValue("last_device_ip", ip)
        self._settings.setValue("routing_active", True)
        self._worker = RouterWorker(ip, self._port_spin.value())
        self._worker.frame_update.connect(self._on_frame_update)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_stopped)
        self._worker.start()
        self._route_toggle.blockSignals(True)
        self._route_toggle.setChecked(True)
        self._route_toggle.blockSignals(False)
        self._combo.setEnabled(False)
        self._port_spin.setEnabled(False)
        self._set_status("routing")

    def _stop(self):
        if self._worker:
            self._worker.stop()

    @Slot(int, float)
    def _on_frame_update(self, total: int, fps: float):
        self._fps_label.setText(f"{total:,} frames  |  {fps:.0f} fps")

    @Slot(str)
    def _on_error(self, msg: str):
        self._set_status("error", msg)

    @Slot()
    def _on_stopped(self):
        self._settings.setValue("routing_active", False)
        self._route_toggle.blockSignals(True)
        self._route_toggle.setChecked(False)
        self._route_toggle.blockSignals(False)
        self._route_toggle.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._combo.setEnabled(True)
        self._port_spin.setEnabled(True)
        if "Error" not in self._status_label.text():
            self._set_status("idle")

    def closeEvent(self, event):
        if self._quitting:
            event.accept()
        else:
            # Minimize to tray instead of closing
            event.ignore()
            self.hide()
            self._tray_show_action.setText("Show")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # Tell Windows this is its own app (not python.exe) — improves taskbar grouping in dev
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)

    app = QApplication(sys.argv)
    app.setWindowIcon(_make_window_icon())
    app.setStyle("Fusion")

    if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window,          QColor(53, 53, 53))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Base,            QColor(35, 35, 35))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(53, 53, 53))
        p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(25, 25, 25))
        p.setColor(QPalette.ColorRole.ToolTipText,     QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Text,            QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Button,          QColor(53, 53, 53))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Link,            QColor(42, 130, 218))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(42, 130, 218))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
        p.setColor(QPalette.ColorRole.PlaceholderText, QColor(170, 170, 170))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text,       QColor(127, 127, 127))
        p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(127, 127, 127))
        app.setPalette(p)

    app.setQuitOnLastWindowClosed(False)   # keep alive when window is hidden

    win = MainWindow()
    # Start hidden — tray icon is the presence indicator
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
