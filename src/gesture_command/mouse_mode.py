"""Mouse mode: control cursor with index finger, tap to click, scroll with two fingers.

Index finger controls cursor: X from tip, Y from DIP joint (stays stable on tap).
Index finger tap down = left click.
Middle finger tap down = right click.
Two fingers extended + hand moving up/down = scroll.
"""

import time
from pynput.mouse import Controller as MouseController, Button
from gesture_command.tracker import Hand
from gesture_command.recognizer import (
    INDEX_TIP, INDEX_DIP, INDEX_MCP, MIDDLE_TIP, MIDDLE_DIP, THUMB_TIP, WRIST,
    is_finger_extended, _dist,
)

_mouse = MouseController()


class MouseMode:
    """Turns the hand into a mouse controller."""

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080,
                 smoothing: float = 0.4, click_threshold: float = 0.04,
                 click_cooldown_ms: float = 400, scroll_speed: float = 3.0):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.smoothing = smoothing
        self.click_threshold = click_threshold
        self.click_cooldown_ms = click_cooldown_ms
        self.scroll_speed = scroll_speed

        self._smooth_x = 0.5
        self._smooth_y = 0.5
        self._last_left_click = 0.0
        self._last_right_click = 0.0
        self._initialized = False

        # Click detection: track tip Y relative to DIP
        self._prev_index_tip_y = 0.0

        # Right click: middle finger tap
        self._prev_middle_y = 0.0

        # Scroll: track wrist Y for hand-level vertical movement
        self._scroll_mode = False
        self._prev_wrist_y = 0.0

    def update(self, hand: Hand):
        """Update mouse position and check for clicks/scroll."""
        lm = hand.landmarks
        now = time.monotonic()

        # Cursor X from index tip, cursor Y from index MCP (knuckle base)
        # MCP is completely stable when tapping — tip and DIP still move
        ix = lm[INDEX_TIP][0]
        iy = lm[INDEX_MCP][1]

        if not self._initialized:
            self._smooth_x = ix
            self._smooth_y = iy
            self._prev_index_tip_y = lm[INDEX_TIP][1]
            self._prev_middle_y = lm[MIDDLE_TIP][1]
            self._prev_wrist_y = lm[WRIST][1]
            self._initialized = True
            return

        # --- Cursor movement ---
        self._smooth_x = self._smooth_x * (1 - self.smoothing) + ix * self.smoothing
        self._smooth_y = self._smooth_y * (1 - self.smoothing) + iy * self.smoothing

        # Map to screen: center 60% of frame -> full screen
        margin = 0.2
        mapped_x = max(0.0, min(1.0, (self._smooth_x - margin) / (1 - 2 * margin)))
        mapped_y = max(0.0, min(1.0, (self._smooth_y - margin) / (1 - 2 * margin)))

        screen_x = int(mapped_x * self.screen_width)
        screen_y = int(mapped_y * self.screen_height)
        _mouse.position = (screen_x, screen_y)

        # --- Detect finger states ---
        index_ext = is_finger_extended(hand, "index")
        middle_ext = is_finger_extended(hand, "middle")

        # --- Scroll mode: index + middle extended, hand moves up/down ---
        wrist_y = lm[WRIST][1]
        if index_ext and middle_ext:
            if not self._scroll_mode:
                self._scroll_mode = True
                self._prev_wrist_y = wrist_y
            else:
                dy = wrist_y - self._prev_wrist_y
                scroll_amount = int(dy * self.scroll_speed * 30)
                if abs(scroll_amount) >= 1:
                    _mouse.scroll(0, -scroll_amount)
                    self._prev_wrist_y = wrist_y
        else:
            self._scroll_mode = False
            self._prev_wrist_y = wrist_y

        # --- Left click: index fingertip taps down ---
        index_tip_y = lm[INDEX_TIP][1]
        index_dy = index_tip_y - self._prev_index_tip_y
        if index_dy > self.click_threshold and not self._scroll_mode:
            if (now - self._last_left_click) * 1000 > self.click_cooldown_ms:
                _mouse.click(Button.left)
                self._last_left_click = now
        self._prev_index_tip_y = index_tip_y

        # --- Right click: middle finger tap down ---
        middle_y = lm[MIDDLE_TIP][1]
        middle_dy = middle_y - self._prev_middle_y
        if middle_dy > self.click_threshold and not self._scroll_mode:
            if (now - self._last_right_click) * 1000 > self.click_cooldown_ms:
                _mouse.click(Button.right)
                self._last_right_click = now
        self._prev_middle_y = middle_y

    def reset(self):
        """Reset state when hand is lost."""
        self._initialized = False
        self._scroll_mode = False
