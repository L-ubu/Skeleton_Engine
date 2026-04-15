"""Continuous gesture recognizers: output a 0.0-1.0 float value per frame.

Unlike discrete gestures (fire once), these map a continuous hand measurement
to a value range that drives actions like volume, brightness, scroll, etc.
"""

import math
from gesture_command.tracker import Hand
from gesture_command.recognizer import (
    THUMB_TIP, INDEX_TIP, INDEX_MCP, MIDDLE_MCP, WRIST,
    is_finger_extended, _dist, _dist_2d,
)


class ContinuousChannel:
    """A named continuous value with smoothing, dead zone, and activation delay.

    activation_ms: the underlying gesture posture must be held for this many ms
    before the channel starts driving its action. Prevents accidental triggers.
    hand_filter: if set ("Left" or "Right"), only this hand drives the channel.
    """

    def __init__(self, name: str, smoothing: float = 0.3, dead_zone: float = 0.02,
                 activation_ms: float = 0, hand_filter: str | None = None):
        self.name = name
        self.smoothing = smoothing
        self.dead_zone = dead_zone
        self.activation_ms = activation_ms
        self.hand_filter = hand_filter  # "Left", "Right", or None (any hand)
        self._value = 0.0
        self._prev_raw = 0.0
        self.active = False
        self._activated = False  # past the activation delay
        self._active_since: float = 0.0

    @property
    def value(self) -> float:
        return self._value

    @property
    def activated(self) -> bool:
        """True when the channel has been active long enough to drive actions."""
        return self._activated

    def update(self, raw: float, active: bool) -> float:
        """Update with a new raw value. Returns smoothed value."""
        import time
        now = time.monotonic()

        if not active:
            self.active = False
            self._activated = False
            self._active_since = 0.0
            return self._value

        if not self.active:
            # Just became active - start activation timer
            self._active_since = now
        self.active = True

        # Check activation delay
        if self.activation_ms > 0:
            elapsed = (now - self._active_since) * 1000
            if elapsed < self.activation_ms:
                self._activated = False
                return self._value
        self._activated = True

        # Dead zone: ignore tiny changes
        if abs(raw - self._prev_raw) < self.dead_zone:
            raw = self._prev_raw
        self._prev_raw = raw

        # Exponential moving average
        self._value = self._value * (1 - self.smoothing) + raw * self.smoothing
        self._value = max(0.0, min(1.0, self._value))
        return self._value


def _pinch_distance_raw(hand: Hand) -> tuple[float, bool]:
    """Pinch distance normalized to 0.0 (closed) - 1.0 (spread).

    Only active when hand is in a pinch-like posture: thumb and index are
    the primary fingers in use, and at least 2 of the other 3 fingers
    are curled. Open palm deactivates the channel.
    """
    dist = _dist(hand.landmarks[THUMB_TIP], hand.landmarks[INDEX_TIP])
    # Normalize: typical pinch range is ~0.02 (touching) to ~0.25 (spread)
    normalized = max(0.0, min(1.0, (dist - 0.02) / 0.23))

    # Activation: middle/ring/pinky should be mostly curled (not an open palm)
    curled_count = 0
    for finger in ("middle", "ring", "pinky"):
        if not is_finger_extended(hand, finger):
            curled_count += 1
    active = curled_count >= 2
    return normalized, active


def _hand_rotation_raw(hand: Hand) -> tuple[float, bool]:
    """Hand roll angle: 0.0 = palm down, 0.5 = sideways, 1.0 = palm up.

    Based on the z-depth difference between index MCP and pinky MCP.
    """
    lm = hand.landmarks
    # Use z-coordinates: when palm faces down, index and pinky z are similar
    # When palm rotates, one side comes forward (lower z)
    index_z = lm[5][2]   # INDEX_MCP
    pinky_z = lm[17][2]  # PINKY_MCP

    # Difference in z normalized. Typical range: -0.1 to 0.1
    diff = pinky_z - index_z
    normalized = max(0.0, min(1.0, (diff + 0.1) / 0.2))
    return normalized, True


def _palm_height_raw(hand: Hand) -> tuple[float, bool]:
    """Vertical position of palm center: 0.0 = bottom, 1.0 = top."""
    lm = hand.landmarks
    # Palm center approximated as average of wrist and middle MCP
    palm_y = (lm[WRIST][1] + lm[MIDDLE_MCP][1]) / 2
    # y is 0 at top, 1 at bottom in MediaPipe normalized coords - invert
    normalized = 1.0 - palm_y
    return max(0.0, min(1.0, normalized)), True


def _hand_spread_raw(hand: Hand) -> tuple[float, bool]:
    """Average distance between fingertips: 0.0 = fist, 1.0 = fully spread."""
    tips = [4, 8, 12, 16, 20]  # fingertip indices
    lm = hand.landmarks
    total_dist = 0.0
    count = 0
    for i in range(len(tips)):
        for j in range(i + 1, len(tips)):
            total_dist += _dist_2d(lm[tips[i]], lm[tips[j]])
            count += 1
    avg_dist = total_dist / count if count > 0 else 0
    # Normalize: typical range ~0.05 (fist) to ~0.4 (spread)
    normalized = max(0.0, min(1.0, (avg_dist - 0.05) / 0.35))
    return normalized, True


def _fist_squeeze_raw(hand: Hand) -> tuple[float, bool]:
    """Average finger curl: 0.0 = open, 1.0 = tight fist."""
    from gesture_command.recognizer import finger_curl_angle
    curls = []
    for finger in ["index", "middle", "ring", "pinky"]:
        angle = finger_curl_angle(hand, finger)
        # Normalize: 0 degrees = straight (curl 0), ~150 degrees = fully curled (curl 1)
        curls.append(max(0.0, min(1.0, angle / 150.0)))
    avg = sum(curls) / len(curls)
    return avg, True


# Registry of continuous gesture functions
CONTINUOUS_GESTURES = {
    "pinch_distance": _pinch_distance_raw,
    "hand_rotation": _hand_rotation_raw,
    "palm_height": _palm_height_raw,
    "hand_spread": _hand_spread_raw,
    "fist_squeeze": _fist_squeeze_raw,
}


class ContinuousRecognizer:
    """Manages all continuous gesture channels with smoothing.

    Channel keys can include a hand filter suffix like "pinch_distance:left".
    The gesture name is the part before ":", and the channel only responds to
    the matching hand.
    """

    def __init__(self):
        self._channels: dict[str, ContinuousChannel] = {}
        self._gesture_for_channel: dict[str, str] = {}  # channel_key -> gesture_name

    def add_channel(self, key: str, smoothing: float = 0.3, dead_zone: float = 0.02,
                    activation_ms: float = 0):
        # Parse "gesture_name:hand" format
        if ":" in key:
            gesture_name, hand_str = key.split(":", 1)
            hand_filter = hand_str.strip().capitalize()  # "left" -> "Left"
        else:
            gesture_name = key
            hand_filter = None

        if gesture_name not in CONTINUOUS_GESTURES:
            print(f"[warning] Unknown continuous gesture: {gesture_name}")
            return

        self._channels[key] = ContinuousChannel(
            key, smoothing, dead_zone, activation_ms, hand_filter=hand_filter
        )
        self._gesture_for_channel[key] = gesture_name

    def update(self, hand: Hand) -> dict[str, float]:
        """Update all channels for this hand. Returns {key: value} only for activated channels."""
        hand_id = hand.handedness  # "Left" or "Right"
        results = {}
        for key, channel in self._channels.items():
            # Skip if this channel is filtered to a different hand
            if channel.hand_filter and channel.hand_filter != hand_id:
                continue

            gesture_name = self._gesture_for_channel[key]
            raw, active = CONTINUOUS_GESTURES[gesture_name](hand)
            value = channel.update(raw, active)
            if channel.activated:
                results[key] = value
        return results

    def get_channels(self) -> dict[str, ContinuousChannel]:
        return dict(self._channels)
