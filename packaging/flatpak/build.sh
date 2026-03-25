#!/usr/bin/env bash
# Lumovee – Flatpak build script
# Produces dist/flatpak/org.lumovee.Lumovee.flatpak
#
# Prerequisites:
#   flatpak install flathub org.freedesktop.Platform//24.08 \
#                           org.freedesktop.Sdk//24.08 \
#                           org.freedesktop.Sdk.Extension.python3//24.08
#   pip install flatpak-pip-generator   # for pinned dependency generation
#
# Usage (from repo root):
#   bash packaging/flatpak/build.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MANIFEST="$ROOT/packaging/flatpak/org.lumovee.Lumovee.yaml"
BUILD_DIR="$ROOT/dist/_build/flatpak"
OUTPUT_DIR="$ROOT/dist/flatpak"

mkdir -p "$OUTPUT_DIR"

echo "==> Building Flatpak…"
flatpak-builder \
    --force-clean \
    --repo="$OUTPUT_DIR/repo" \
    "$BUILD_DIR" \
    "$MANIFEST"

echo ""
echo "==> Bundling to single-file .flatpak…"
flatpak build-bundle \
    "$OUTPUT_DIR/repo" \
    "$OUTPUT_DIR/org.lumovee.Lumovee.flatpak" \
    org.lumovee.Lumovee

echo ""
echo "==> Done.  Bundle written to dist/flatpak/org.lumovee.Lumovee.flatpak"
echo "    Install with:  flatpak install dist/flatpak/org.lumovee.Lumovee.flatpak"
