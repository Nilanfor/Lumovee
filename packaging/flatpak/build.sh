#!/usr/bin/env bash
# Lumovee – Flatpak build script
# Automatically installs missing runtimes, builds, and bundles the Flatpak.
#
# Usage (from anywhere in the repo):
#   bash packaging/flatpak/build.sh
#
# Optional flags:
#   --install   Also install the resulting .flatpak for the current user

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MANIFEST="$ROOT/packaging/flatpak/org.lumovee.Lumovee.yaml"
BUILD_DIR="$ROOT/dist/_build/flatpak"
REPO_DIR="$ROOT/dist/flatpak/repo"
BUNDLE="$ROOT/dist/flatpak/org.lumovee.Lumovee.flatpak"
APP_ID="org.lumovee.Lumovee"

ALSO_INSTALL=false
for arg in "$@"; do
    [[ "$arg" == "--install" ]] && ALSO_INSTALL=true
done

# ── Prerequisites ──────────────────────────────────────────────────────────────

if ! command -v flatpak &>/dev/null; then
    echo "Error: flatpak is not installed." >&2
    exit 1
fi

if ! command -v flatpak-builder &>/dev/null; then
    echo "Error: flatpak-builder is not installed." >&2
    echo "  sudo pacman -S flatpak-builder" >&2
    exit 1
fi

# ── Flathub remote ────────────────────────────────────────────────────────────

if ! flatpak remote-list 2>/dev/null | grep -q "^flathub"; then
    echo "==> Adding Flathub remote…"
    flatpak remote-add --user --if-not-exists flathub \
        https://dl.flathub.org/repo/flathub.flatpakrepo
fi

# ── Build ─────────────────────────────────────────────────────────────────────

mkdir -p "$(dirname "$BUNDLE")"

echo ""
echo "==> Building Flatpak…"
flatpak-builder \
    --force-clean \
    --install-deps-from=flathub \
    --repo="$REPO_DIR" \
    "$BUILD_DIR" \
    "$MANIFEST"

# ── Bundle ────────────────────────────────────────────────────────────────────

echo ""
echo "==> Bundling…"
flatpak build-bundle \
    "$REPO_DIR" \
    "$BUNDLE" \
    "$APP_ID"

echo ""
echo "Done. Bundle: $BUNDLE"

# ── Install (optional) ────────────────────────────────────────────────────────

if [[ "$ALSO_INSTALL" == true ]]; then
    echo ""
    echo "==> Installing…"
    flatpak install --user --noninteractive "$BUNDLE"

    # Rebuild KDE's application menu cache so the entry appears immediately
    if command -v kbuildsycoca6 &>/dev/null; then
        echo "==> Refreshing KDE menu cache…"
        kbuildsycoca6 2>/dev/null
    fi

    echo ""
    echo "==> Launching…"
    flatpak run "$APP_ID"
else
    echo "    Install with: flatpak install --user $BUNDLE"
    echo "    Run with:     flatpak run $APP_ID"
fi
