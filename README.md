# Lumovee

A lightweight cross-platform system-tray app that bridges [Hyperion](https://hyperion-project.org/) / [HyperHDR](https://github.com/awawa-dev/HyperHDR) to DreamView-compatible Govee LED strips over the local network and allows for basic device control.

Hyperion/HyperHDR capture your screen and send the resulting per-LED colors as **UDP Raw** frames. Lumovee receives those frames and forwards them to a Govee device using the Govee LAN API (Razer/DreamView protocol), giving you ambient bias lighting driven by your own capture software.

## Disclaimer: The application right now is mostly vibe-coded as a Proof of Concept prototype, but is as of right now fully functional with all advertised features. It will get a full Kirigami-based refactor by me in the future.

## Features

- Auto-discovers Govee devices on the LAN
- Per-device controls: power toggle, brightness slider, custom name
- DreamView tab: route UDP Raw frames from Hyperion/HyperHDR to a selected device
- Settings tab: optional autostart with the system
- Routing state is restored automatically on next launch
- Minimises to the system tray

## Tested Setups

| Govee Device | CachyOS | Windows |
| ------------ | ------- | ------- |
| G1           | ✅      | ✅      |

## Requirements

- Python 3.11+
- PySide6

```
pip install PySide6
```

> The Govee LAN API must be enabled for an LED device to enable DreamView control.

## Running

```bash
cd src
python ui.py
```

The app starts minimised to the tray. Click the tray icon to open the window.

## How it works

1. **Devices tab** — click the scan button (↻) to discover Govee devices on your LAN. Each discovered device appears as a card with power and brightness controls.
2. **DreamView tab** — select a device from the dropdown, set the UDP Raw port to match the output port configured in Hyperion/HyperHDR, then flip the toggle to start routing.
3. **Settings tab** — optionally enable autostart with the system. If routing was active when the app was last closed, it resumes automatically on the next launch.

## License

[MIT](LICENSE) © 2026 Nils-André Forjahn

## Building

### Windows installer

Requires [PyInstaller](https://pyinstaller.org/) and [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
pip install pyinstaller
.\packaging\windows\build.ps1
# → dist\windows\Lumovee-Setup-1.0.exe
```

### Flatpak

Requires `flatpak-builder` and the freedesktop runtime.

```bash
flatpak install flathub \
    org.freedesktop.Platform//24.08 \
    org.freedesktop.Sdk//24.08 \
    org.freedesktop.Sdk.Extension.python3//24.08
bash packaging/flatpak/build.sh
# → dist/flatpak/org.lumovee.Lumovee.flatpak
```

> **Note:** The Flatpak manifest includes a placeholder for the PySide6 pip wheel. For a fully reproducible offline build, use `flatpak-pip-generator` to generate a pinned dependencies file and reference it from the manifest (see the comment inside `org.lumovee.Lumovee.yaml`).

## Project layout

```
src/
  ui.py                    # PySide6 tray application (entry point)
  govee/
    device.py              # LAN UDP discovery and basic device commands
    razer.py               # Razer/DreamView per-segment protocol
packaging/
  windows/
    lumovee.spec           # PyInstaller spec
    installer.iss          # Inno Setup script
    build.ps1              # Windows build orchestration
  flatpak/
    org.lumovee.Lumovee.yaml     # flatpak-builder manifest
    org.lumovee.Lumovee.desktop  # desktop entry
    org.lumovee.Lumovee.metainfo.xml  # AppStream metadata
    build.sh               # Flatpak build script
tools/                     # standalone dev/debug scripts (not required to run the app)
  router.py                # headless CLI router (fallback for server environments)
  demo.py                  # interactive segment layout calibration and animation showcase
  capture.py               # raw UDP packet capture for protocol debugging (requires admin)
```
