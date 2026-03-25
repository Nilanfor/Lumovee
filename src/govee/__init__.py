from .device import (
    DEVICE_SKU, DEVICE_IP,
    discover, discover_all,
    turn_on, turn_off, set_brightness, set_color, get_status,
    play_scene, set_segments,
    animate_chase_framebased, animate_chase_device,
)
from .razer import (
    NUM_SEGMENTS,
    SEGS_LEFT, SEGS_TOP, SEGS_RIGHT, SEGS_BOTTOM, SEGS_CORNERS,
    razer_start, razer_stop, set_segments_razer,
)
