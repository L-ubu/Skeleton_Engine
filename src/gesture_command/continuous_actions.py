"""Continuous action execution: volume, brightness, scroll, zoom.

These receive a 0.0-1.0 float value and translate it to OS-level controls.
Rate-limited to avoid spamming the OS.
"""

import subprocess
import time
import Quartz
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Controller as MouseController


_keyboard = KeyboardController()
_mouse = MouseController()


class ContinuousAction:
    """Base for continuous actions with rate limiting."""

    def __init__(self, update_interval_ms: float = 100, invert: bool = False):
        self.update_interval_ms = update_interval_ms
        self.invert = invert
        self._last_update = 0.0
        self._last_value = -1.0

    def execute(self, value: float):
        now = time.monotonic()
        elapsed = (now - self._last_update) * 1000
        if elapsed < self.update_interval_ms:
            return

        if self.invert:
            value = 1.0 - value

        if abs(value - self._last_value) < 0.01:
            return

        self._last_update = now
        old_value = self._last_value
        self._last_value = value
        self._apply(value, old_value)

    def _apply(self, value: float, old_value: float):
        raise NotImplementedError


def _send_media_key(key_type: int):
    """Send a macOS media key event via Quartz. key_type: 2=brightness_up, 3=brightness_down."""
    # Key down
    ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        14, (0, 0), 0xa00, 0, 0, 0, 8, (key_type << 16) | (0xa << 8), -1)
    Quartz.CGEventPost(0, ev.CGEvent())
    # Key up
    ev = Quartz.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        14, (0, 0), 0xa00, 0, 0, 0, 8, (key_type << 16) | (0xb << 8), -1)
    Quartz.CGEventPost(0, ev.CGEvent())


class VolumeAction(ContinuousAction):
    """Set macOS system volume (0-100) via osascript."""

    def __init__(self, **kwargs):
        kwargs.setdefault("update_interval_ms", 200)
        super().__init__(**kwargs)

    def _apply(self, value: float, old_value: float):
        vol = int(value * 100)
        subprocess.Popen(
            ["osascript", "-e", f"set volume output volume {vol}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


class BrightnessAction(ContinuousAction):
    """Control macOS screen brightness using HID media key simulation.

    Maps value changes to brightness up/down key taps. Larger changes
    send more taps for faster adjustment.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("update_interval_ms", 120)
        super().__init__(**kwargs)

    def _apply(self, value: float, old_value: float):
        if old_value < 0:
            return  # Skip first frame
        diff = value - old_value
        # Each tap is roughly 1/16 of full brightness range
        taps = int(abs(diff) * 16)
        taps = max(0, min(taps, 3))  # Cap at 3 taps per update to avoid jumps
        if taps == 0:
            return
        key_type = 2 if diff > 0 else 3  # 2 = brightness up, 3 = brightness down
        for _ in range(taps):
            _send_media_key(key_type)


class ScrollAction(ContinuousAction):
    """Scroll at a rate proportional to value. Center (0.5) = no scroll."""

    def __init__(self, direction: str = "vertical", **kwargs):
        super().__init__(**kwargs)
        self.direction = direction

    def _apply(self, value: float, old_value: float):
        speed = int((value - 0.5) * 10)
        if abs(speed) < 1:
            return
        if self.direction == "vertical":
            _mouse.scroll(0, speed)
        else:
            _mouse.scroll(speed, 0)


class ZoomAction(ContinuousAction):
    """Zoom via cmd+plus/cmd+minus based on value changes."""

    def _apply(self, value: float, old_value: float):
        if old_value < 0:
            return
        diff = value - old_value
        from pynput.keyboard import KeyCode
        if diff > 0.03:
            with _keyboard.pressed(Key.cmd):
                _keyboard.press(KeyCode.from_char("="))
                _keyboard.release(KeyCode.from_char("="))
        elif diff < -0.03:
            with _keyboard.pressed(Key.cmd):
                _keyboard.press(KeyCode.from_char("-"))
                _keyboard.release(KeyCode.from_char("-"))


class AppleScriptAction(ContinuousAction):
    """Run arbitrary AppleScript with {value} placeholder."""

    def __init__(self, script: str, **kwargs):
        super().__init__(**kwargs)
        self.script = script

    def _apply(self, value: float, old_value: float):
        rendered = self.script.replace("{value}", str(value))
        subprocess.Popen(
            ["osascript", "-e", rendered],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


CONTINUOUS_ACTION_TYPES = {
    "volume": VolumeAction,
    "brightness": BrightnessAction,
    "scroll": ScrollAction,
    "zoom": ZoomAction,
    "applescript": AppleScriptAction,
}


def create_continuous_action(action_config: dict) -> ContinuousAction:
    """Create a continuous action from config dict."""
    action_type = action_config.get("type")
    if action_type not in CONTINUOUS_ACTION_TYPES:
        raise ValueError(f"Unknown continuous action type: {action_type}")

    cls = CONTINUOUS_ACTION_TYPES[action_type]
    kwargs = {}

    if "update_interval_ms" in action_config:
        kwargs["update_interval_ms"] = action_config["update_interval_ms"]
    if "invert" in action_config:
        kwargs["invert"] = action_config["invert"]
    if action_type == "scroll" and "direction" in action_config:
        kwargs["direction"] = action_config["direction"]
    if action_type == "applescript" and "script" in action_config:
        kwargs["script"] = action_config["script"]

    return cls(**kwargs)
