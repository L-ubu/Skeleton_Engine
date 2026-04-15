"""Gesture filtering: dwell time, cooldown, debounce, state machine.

Prevents false triggers and makes gesture recognition feel intentional.
"""

import time
from enum import Enum


class GestureState(Enum):
    IDLE = "idle"
    DETECTING = "detecting"  # gesture seen, counting dwell time
    FIRED = "fired"          # action was triggered
    COOLDOWN = "cooldown"    # waiting before allowing re-trigger


class GestureFilter:
    """State machine for a single gesture slot.

    Tracks one gesture at a time through: idle -> detecting -> fired -> cooldown -> idle
    """

    def __init__(
        self,
        dwell_ms: float = 300,
        cooldown_ms: float = 500,
        confidence_threshold: float = 0.7,
        debounce_frames: int = 2,
    ):
        self.dwell_ms = dwell_ms
        self.cooldown_ms = cooldown_ms
        self.confidence_threshold = confidence_threshold
        self.debounce_frames = debounce_frames

        self._state = GestureState.IDLE
        self._current_gesture: str | None = None
        self._detect_start: float = 0.0
        self._cooldown_start: float = 0.0
        self._consecutive_frames: int = 0
        self._last_gesture: str | None = None

    @property
    def state(self) -> GestureState:
        return self._state

    @property
    def current_gesture(self) -> str | None:
        return self._current_gesture

    @property
    def dwell_progress(self) -> float:
        """0.0 to 1.0 progress through dwell time. Only meaningful in DETECTING state."""
        if self._state != GestureState.DETECTING:
            return 0.0
        elapsed = (time.monotonic() - self._detect_start) * 1000
        return min(1.0, elapsed / self.dwell_ms) if self.dwell_ms > 0 else 1.0

    def update(self, gesture: str | None, confidence: float) -> str | None:
        """Feed a recognition result. Returns gesture name if it should fire this frame, else None.

        Call this once per frame with the recognized gesture (or None if nothing detected).
        """
        now = time.monotonic()

        # Apply confidence threshold
        if gesture is not None and confidence < self.confidence_threshold:
            gesture = None

        if self._state == GestureState.COOLDOWN:
            elapsed = (now - self._cooldown_start) * 1000
            if elapsed >= self.cooldown_ms:
                self._state = GestureState.IDLE
                self._current_gesture = None
            else:
                return None

        if self._state == GestureState.IDLE:
            if gesture is not None:
                if gesture == self._last_gesture:
                    self._consecutive_frames += 1
                else:
                    self._consecutive_frames = 1
                    self._last_gesture = gesture

                if self._consecutive_frames >= self.debounce_frames:
                    self._state = GestureState.DETECTING
                    self._current_gesture = gesture
                    self._detect_start = now
            else:
                self._consecutive_frames = 0
                self._last_gesture = None
            return None

        if self._state == GestureState.DETECTING:
            if gesture != self._current_gesture:
                # Gesture changed or lost - reset
                self._state = GestureState.IDLE
                self._current_gesture = None
                self._consecutive_frames = 0
                self._last_gesture = None
                return None

            elapsed = (now - self._detect_start) * 1000
            if elapsed >= self.dwell_ms:
                # Fire!
                self._state = GestureState.COOLDOWN
                self._cooldown_start = now
                fired = self._current_gesture
                return fired

        if self._state == GestureState.FIRED:
            # Transition to cooldown
            self._state = GestureState.COOLDOWN
            self._cooldown_start = now

        return None


class FilterPipeline:
    """Manages gesture filters with per-gesture overrides."""

    def __init__(self, default_dwell_ms=300, default_cooldown_ms=500,
                 confidence_threshold=0.7, debounce_frames=2):
        self._defaults = {
            "dwell_ms": default_dwell_ms,
            "cooldown_ms": default_cooldown_ms,
            "confidence_threshold": confidence_threshold,
            "debounce_frames": debounce_frames,
        }
        self._filters: dict[str, GestureFilter] = {}  # per-hand filters
        self._overrides: dict[str, dict] = {}  # per-gesture setting overrides

    def set_gesture_overrides(self, gesture_name: str, **kwargs):
        """Set per-gesture filter settings (dwell_ms, cooldown_ms, etc.)."""
        self._overrides[gesture_name] = kwargs

    def _get_filter(self, hand_id: str) -> GestureFilter:
        if hand_id not in self._filters:
            self._filters[hand_id] = GestureFilter(**self._defaults)
        return self._filters[hand_id]

    def update(self, hand_id: str, gesture: str | None, confidence: float) -> str | None:
        """Process a recognition result for a specific hand. Returns fired gesture or None."""
        filt = self._get_filter(hand_id)

        # Apply per-gesture overrides dynamically
        if gesture and gesture in self._overrides:
            overrides = self._overrides[gesture]
            filt.dwell_ms = overrides.get("dwell_ms", self._defaults["dwell_ms"])
            filt.cooldown_ms = overrides.get("cooldown_ms", self._defaults["cooldown_ms"])
        else:
            filt.dwell_ms = self._defaults["dwell_ms"]
            filt.cooldown_ms = self._defaults["cooldown_ms"]

        return filt.update(gesture, confidence)

    def get_state(self, hand_id: str) -> tuple[GestureState, float]:
        """Get (state, dwell_progress) for a hand."""
        if hand_id not in self._filters:
            return GestureState.IDLE, 0.0
        f = self._filters[hand_id]
        return f.state, f.dwell_progress
