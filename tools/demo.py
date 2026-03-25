"""
demo.py - Interactive demos and layout calibration for the Govee H6609.

Usage:
  python tools/demo.py layout     # step through sides/corners to verify segment mapping
  python tools/demo.py animate    # multi-effect animation showcase
  python tools/demo.py test       # static test patterns with prompts
"""

import sys
import os
import time
import math
import colorsys
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from govee import (
    discover, DEVICE_SKU, turn_on, set_brightness,
    razer_start, razer_stop, set_segments_razer, NUM_SEGMENTS,
    SEGS_LEFT, SEGS_TOP, SEGS_RIGHT, SEGS_BOTTOM, SEGS_CORNERS,
)


def _hsv(h, s=1.0, v=1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


# --- Layout calibration ---

def test_layout(ip):
    """Color each side to verify the segment→physical mapping."""
    razer_start(ip)
    time.sleep(0.1)

    sides = [
        ("Bottom (red)",   SEGS_BOTTOM, (255,   0,   0)),
        ("Left (green)",   SEGS_LEFT,   (  0, 255,   0)),
        ("Top (blue)",     SEGS_TOP,    (  0,   0, 255)),
        ("Right (yellow)", SEGS_RIGHT,  (255, 200,   0)),
    ]

    print("\n[All sides]  Bottom=red  Left=green  Top=blue  Right=yellow  Corners=white")
    colors = [(0, 0, 0)] * NUM_SEGMENTS
    for _, segs, rgb in sides:
        for i in segs:
            colors[i] = rgb
    for i in SEGS_CORNERS:
        colors[i] = (255, 255, 255)
    set_segments_razer(ip, colors)
    input("  Correct sides? Corners white at the bends? Enter to step through...")

    for label, segs, rgb in sides:
        colors = [(0, 0, 0)] * NUM_SEGMENTS
        for i in segs:
            colors[i] = rgb
        set_segments_razer(ip, colors)
        input(f"  [{label}]  correct position & direction? Enter...")

    print("  Stepping through segments 0→32 individually...")
    for i in range(NUM_SEGMENTS):
        colors = [(0, 0, 0)] * NUM_SEGMENTS
        colors[i] = (255, 255, 255)
        set_segments_razer(ip, colors)
        input(f"  Segment {i:2d} — which physical position? Enter...")

    razer_stop(ip)


# --- Static test patterns ---

def test_patterns(ip):
    razer_start(ip)
    time.sleep(0.1)

    print("\n[A] First segment red, last blue")
    colors = [(0, 0, 0)] * NUM_SEGMENTS
    colors[0]  = (255, 0, 0)
    colors[-1] = (0, 0, 255)
    set_segments_razer(ip, colors)
    input("  Enter to continue...")

    print("\n[B] All red")
    set_segments_razer(ip, [(255, 0, 0)] * NUM_SEGMENTS)
    input("  Enter to continue...")

    print("\n[C] All green")
    set_segments_razer(ip, [(0, 255, 0)] * NUM_SEGMENTS)
    input("  Enter to continue...")

    razer_stop(ip)


# --- Animation showcase ---

def animate(ip, secs=6, fps=30):
    N, dt = NUM_SEGMENTS, 1 / fps

    def run(name, gen):
        print(f"  [{name}]  Ctrl+C to skip")
        deadline = time.time() + secs
        try:
            while time.time() < deadline:
                set_segments_razer(ip, next(gen))
                time.sleep(dt)
        except KeyboardInterrupt:
            print("    skipped.")

    def rainbow_wave():
        step = 0
        while True:
            yield [_hsv((i / N + step / (fps * 3)) % 1.0) for i in range(N)]
            step += 1

    def warm_breathe():
        t = 0
        while True:
            v = (math.sin(2 * math.pi * t / (fps * 2)) + 1) / 2
            yield [(int(255 * v), int(180 * v), int(60 * v))] * N
            t += 1

    def comet():
        TAIL, step = 8, 0
        while True:
            frame = [(0, 0, 0)] * N
            for t in range(TAIL):
                frac = (TAIL - t) / TAIL
                frame[(step - t) % N] = (int(255 * frac), int(120 * frac ** 2), 0)
            yield frame
            step += 1

    def dual_comets():
        TAIL, half, step = 5, N // 2, 0
        while True:
            frame = [(0, 0, 0)] * N
            for t in range(TAIL):
                frac = (TAIL - t) / TAIL
                frame[(step - t) % half] = (0, int(180 * frac), int(255 * frac))
                frame[N - 1 - (step - t) % half] = (int(255 * frac), 0, int(180 * frac))
            yield frame
            step += 1

    def police():
        half, t = N // 2, 0
        patterns = [
            [(200, 0, 0)] * half + [(0, 0, 0)] * (N - half),
            [(0, 0, 0)] * half + [(0, 0, 200)] * (N - half),
            [(200, 0, 0)] * half + [(0, 0, 0)] * (N - half),
            [(0, 0, 0)] * N,
        ]
        while True:
            yield patterns[(t // max(1, fps // 4)) % len(patterns)]
            t += 1

    def sparkle():
        step = 0
        while True:
            bg = _hsv(step / (fps * 8), 0.7, 0.3)
            frame = [bg] * N
            for _ in range(3):
                frame[random.randrange(N)] = (255, 255, 255)
            yield frame
            step += 1

    print("=== Animation showcase ===  (Ctrl+C twice to quit)")
    razer_start(ip)
    time.sleep(0.1)
    try:
        run("Rainbow wave",   rainbow_wave())
        run("Warm breathing", warm_breathe())
        run("Orange comet",   comet())
        run("Dual comets",    dual_comets())
        run("Police flash",   police())
        run("Sparkle",        sparkle())
    except KeyboardInterrupt:
        print("\nExiting.")
    finally:
        razer_stop(ip)


# --- Entry point ---

COMMANDS = {"layout": test_layout, "animate": animate, "test": test_patterns}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "animate"
    if cmd not in COMMANDS:
        print(f"Usage: python tools/demo.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)

    print("Discovering Govee device...")
    ip = discover(sku=DEVICE_SKU)
    if not ip:
        print("Device not found.")
        sys.exit(1)
    print(f"Device at {ip}")
    turn_on(ip)
    set_brightness(ip, 100)
    time.sleep(0.5)

    COMMANDS[cmd](ip)
