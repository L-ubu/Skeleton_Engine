"""Main engine: ties camera, tracking, recognition, filtering, and actions together."""

import cv2
import time
import threading
from pynput import keyboard

from gesture_command.capture import Camera
from gesture_command.tracker import HandTracker, draw_landmarks
from gesture_command.recognizer import recognize, extended_fingers
from gesture_command.continuous import ContinuousRecognizer
from gesture_command.continuous_actions import create_continuous_action, ContinuousAction
from gesture_command.filters import FilterPipeline, GestureState
from gesture_command.actions import execute_action
from gesture_command.mapper import Config


# Colors (BGR)
GREEN = (0, 255, 0)
YELLOW = (0, 220, 255)
RED = (0, 0, 255)
WHITE = (255, 255, 255)
DARK_BG = (30, 30, 30)


def _confidence_color(conf: float) -> tuple:
    if conf >= 0.85:
        return GREEN
    if conf >= 0.7:
        return YELLOW
    return RED


def _fire_action_async(action: dict):
    """Run an action on a background thread so it never blocks the main loop."""
    threading.Thread(target=execute_action, args=(action,), daemon=True).start()


class Engine:
    def __init__(self, config: Config, debug: bool = True, detect_every: int = 2,
                 active_gestures: list[str] | None = None, mouse_mode: bool = False):
        self.config = config
        self.debug = debug
        self.detect_every = detect_every
        self.enabled = config.start_enabled
        self.skeleton_only = False
        self.mouse_mode = mouse_mode
        self._running = False

        # If active_gestures specified, only those fire actions.
        # None means all configured gestures are active.
        self.active_gestures = set(active_gestures) if active_gestures else None

        # Components
        self.camera = Camera(camera_index=config.camera_index)
        self.tracker = HandTracker(max_hands=2)
        self.filters = FilterPipeline(
            default_dwell_ms=config.default_dwell_ms,
            default_cooldown_ms=config.default_cooldown_ms,
            confidence_threshold=config.confidence_threshold,
        )
        self.continuous_recognizer = ContinuousRecognizer()
        self.continuous_actions: dict[str, ContinuousAction] = {}

        # Mouse mode
        self._mouse_controller = None
        if self.mouse_mode:
            from gesture_command.mouse_mode import MouseMode
            self._mouse_controller = MouseMode()

        self._setup_from_config()

    def _setup_from_config(self):
        """Wire up gesture overrides and continuous channels from config."""
        for gesture_name in self.config.get_discrete_gestures():
            # Skip if not in active set
            if self.active_gestures is not None and gesture_name not in self.active_gestures:
                continue
            overrides = self.config.get_gesture_overrides(gesture_name)
            if overrides:
                self.filters.set_gesture_overrides(gesture_name, **overrides)

        for channel_name, mapping in self.config.get_continuous_mappings().items():
            smoothing = mapping.get("smoothing", 0.3)
            dead_zone = mapping.get("dead_zone", 0.02)
            activation_ms = mapping.get("activation_ms", 0)
            self.continuous_recognizer.add_channel(channel_name, smoothing, dead_zone, activation_ms)

            action_config = dict(mapping.get("action", {}))
            if "update_interval_ms" in mapping:
                action_config["update_interval_ms"] = mapping["update_interval_ms"]
            if "invert" in mapping:
                action_config["invert"] = mapping["invert"]
            self.continuous_actions[channel_name] = create_continuous_action(action_config)

    def _setup_hotkey(self):
        """Register global toggle hotkey."""
        hotkey_str = self.config.toggle_hotkey
        parts = hotkey_str.lower().split("+")
        pynput_parts = []
        for p in parts:
            p = p.strip()
            if p in ("cmd", "command"):
                pynput_parts.append("<cmd>")
            elif p in ("ctrl", "control"):
                pynput_parts.append("<ctrl>")
            elif p in ("alt", "option"):
                pynput_parts.append("<alt>")
            elif p == "shift":
                pynput_parts.append("<shift>")
            else:
                pynput_parts.append(p)
        pynput_combo = "+".join(pynput_parts)

        def on_toggle():
            self.enabled = not self.enabled
            state = "ENABLED" if self.enabled else "PAUSED"
            print(f"\n[hotkey] Gesture recognition {state}")
            try:
                import subprocess
                subprocess.Popen([
                    "osascript", "-e",
                    f'display notification "Gesture recognition {state}" with title "GestureCommand"'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        self._hotkey_listener = keyboard.GlobalHotKeys({pynput_combo: on_toggle})
        self._hotkey_listener.start()

    def run(self):
        """Main engine loop."""
        self._running = True
        self._setup_hotkey()

        print("Starting GestureCommand engine...")
        if self.mouse_mode:
            print("MOUSE MODE: index finger = cursor, tap index = left click, tap middle = right click")
        if self.active_gestures:
            print(f"Active gestures: {', '.join(sorted(self.active_gestures))}")
        else:
            configured = list(self.config.get_discrete_gestures().keys())
            print(f"Active gestures: {', '.join(configured) if configured else 'none'}")
        if self.debug:
            print("Debug window enabled.")
            print("  'q'        = quit")
            print("  ESC        = toggle pause")
            print("  's'        = toggle skeleton-only view")
            print("  'm'        = toggle mouse mode")
        print(f"Toggle hotkey: {self.config.toggle_hotkey}")
        print(f"Recognition: {'ENABLED' if self.enabled else 'PAUSED'}")
        print()

        self.camera.open()
        prev_time = time.time()
        fps = 0.0
        frame_count = 0
        cached_hands = []
        cached_gesture_info = []
        cached_continuous = {}
        # Throttle config reload to every 60 frames instead of every frame
        reload_counter = 0

        try:
            while self._running:
                frame = self.camera.read()
                if frame is None:
                    continue

                frame = cv2.flip(frame, 1)
                frame_count += 1

                # Config hot-reload (check every ~2 seconds, not every frame)
                reload_counter += 1
                if reload_counter >= 60:
                    reload_counter = 0
                    self.config.check_reload()

                # Detection (every Nth frame)
                if frame_count % self.detect_every == 0:
                    cached_hands = self.tracker.process(frame)
                    cached_gesture_info = []
                    cached_continuous = {}

                    for hand in cached_hands:
                        hand_id = hand.handedness

                        # Mouse mode: first hand drives cursor
                        if self.mouse_mode and self.enabled and self._mouse_controller:
                            self._mouse_controller.update(hand)

                        result = recognize(hand, self.config.confidence_threshold)
                        fingers = extended_fingers(hand)
                        gesture_name = result[0] if result else None
                        confidence = result[1] if result else 0.0

                        # Filter out gestures not in active set
                        effective_gesture = gesture_name
                        if effective_gesture and self.active_gestures:
                            if effective_gesture not in self.active_gestures:
                                effective_gesture = None

                        fired = None
                        if self.enabled and not self.mouse_mode:
                            fired = self.filters.update(hand_id, effective_gesture, confidence if effective_gesture else 0.0)

                        state, dwell_progress = self.filters.get_state(hand_id)
                        cached_gesture_info.append((
                            hand_id, gesture_name, confidence, fingers,
                            state, dwell_progress, fired
                        ))

                        # Fire discrete action (async)
                        if fired and self.enabled:
                            action = self.config.get_gesture_action(fired)
                            if action:
                                print(f"[action] {fired} -> {action}")
                                _fire_action_async(action)

                        # Continuous gestures (skip in mouse mode)
                        if self.enabled and not self.mouse_mode:
                            values = self.continuous_recognizer.update(hand)
                            cached_continuous.update(values)

                    # Execute continuous actions once per frame
                    if self.enabled and cached_continuous and not self.mouse_mode:
                        for ch_name, ch_value in cached_continuous.items():
                            if ch_name in self.continuous_actions:
                                self.continuous_actions[ch_name].execute(ch_value)

                    # Reset mouse when no hands
                    if not cached_hands and self._mouse_controller:
                        self._mouse_controller.reset()

                # FPS
                now = time.time()
                dt = now - prev_time
                prev_time = now
                fps = 0.9 * fps + 0.1 * (1.0 / dt if dt > 0 else 0)

                # Debug overlay
                if self.debug:
                    self._draw_debug(frame, fps, cached_hands, cached_gesture_info, cached_continuous)
                    cv2.imshow("GestureCommand", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break
                    elif key == 27:  # ESC = toggle pause
                        self.enabled = not self.enabled
                        state = "ENABLED" if self.enabled else "PAUSED"
                        print(f"[hotkey] Gesture recognition {state}")
                    elif key == ord('s'):
                        self.skeleton_only = not self.skeleton_only
                        mode = "SKELETON ONLY" if self.skeleton_only else "CAMERA"
                        print(f"[view] Switched to {mode}")
                    elif key == ord('m'):
                        self.mouse_mode = not self.mouse_mode
                        if self.mouse_mode and not self._mouse_controller:
                            from gesture_command.mouse_mode import MouseMode
                            self._mouse_controller = MouseMode()
                        if self._mouse_controller:
                            self._mouse_controller.reset()
                        state = "ON" if self.mouse_mode else "OFF"
                        print(f"[mouse] Mouse mode {state}")
                else:
                    time.sleep(0.001)

        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self._running = False
            self.camera.close()
            self.tracker.close()
            self._hotkey_listener.stop()
            if self.debug:
                cv2.destroyAllWindows()

    def _draw_debug(self, frame, fps, hands, gesture_info, continuous):
        """Draw the full debug overlay."""
        h, w = frame.shape[:2]

        # Skeleton-only mode: black background
        if self.skeleton_only:
            frame[:] = 0

        # Status indicator (enabled/paused)
        status_color = GREEN if self.enabled else RED
        status_text = "ACTIVE" if self.enabled else "PAUSED"
        cv2.circle(frame, (w - 20, 20), 8, status_color, -1, cv2.LINE_AA)
        cv2.putText(frame, status_text, (w - 90, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, status_color, 1, cv2.LINE_AA)

        # Mode indicators
        if self.skeleton_only:
            cv2.putText(frame, "SKELETON [s]", (w - 130, 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 120, 120), 1, cv2.LINE_AA)
        if self.mouse_mode:
            cv2.putText(frame, "MOUSE [m]", (w - 105, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, YELLOW, 1, cv2.LINE_AA)

        # Info panel background (simple filled rect, no numpy blend)
        panel_h = max(45 + len(gesture_info) * 55, 80)
        cv2.rectangle(frame, (0, 0), (340, panel_h), DARK_BG, -1)

        # FPS and hand count
        cv2.putText(frame, f"FPS: {fps:.0f}", (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)
        cv2.putText(frame, f"Hands: {len(hands)}", (120, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)

        # Per-hand info
        for i, info in enumerate(gesture_info):
            hand_id, gesture_name, confidence, fingers, state, dwell_progress, fired = info
            y_base = 50 + i * 55

            cv2.putText(frame, f"{hand_id}:", (10, y_base),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)

            if gesture_name:
                color = _confidence_color(confidence)
                cv2.putText(frame, gesture_name.upper(), (10, y_base + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
                cv2.putText(frame, f"{confidence:.0%}", (220, y_base + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
            else:
                cv2.putText(frame, "---", (10, y_base + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 1, cv2.LINE_AA)

            # Dwell progress bar
            if state == GestureState.DETECTING and dwell_progress > 0:
                bar_x, bar_y, bar_w = 10, y_base + 30, 200
                cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 4), (60, 60, 60), -1)
                cv2.rectangle(frame, (bar_x, bar_y), (bar_x + int(bar_w * dwell_progress), bar_y + 4), YELLOW, -1)

            if fired:
                cv2.putText(frame, "FIRED!", (270, y_base + 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, GREEN, 2, cv2.LINE_AA)

            # Finger dots
            finger_labels = [("T", "thumb"), ("I", "index"), ("M", "middle"), ("R", "ring"), ("P", "pinky")]
            for j, (label, key) in enumerate(finger_labels):
                x = 220 + j * 22
                dot_color = GREEN if fingers.get(key, False) else RED
                cv2.circle(frame, (x, y_base - 5), 6, dot_color, -1, cv2.LINE_AA)
                cv2.putText(frame, label, (x - 4, y_base - 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.25, WHITE, 1, cv2.LINE_AA)

        # Draw hand skeletons + gesture labels near hands
        for idx, hand in enumerate(hands):
            draw_landmarks(frame, hand)
            if idx < len(gesture_info):
                g_name, g_conf = gesture_info[idx][1], gesture_info[idx][2]
                if g_name:
                    wrist = hand.landmarks[0]
                    px = int(wrist[0] * w)
                    py = int(wrist[1] * h) - 20
                    color = _confidence_color(g_conf)
                    text = f"{g_name.upper()} ({g_conf:.0%})"
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(frame, (px - 5, py - th - 5), (px + tw + 5, py + 5), DARK_BG, -1)
                    cv2.putText(frame, text, (px, py),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        # Continuous values bar (bottom)
        if continuous:
            bar_y = h - 25
            cv2.rectangle(frame, (0, bar_y - 8), (w, h), (20, 20, 20), -1)
            x_offset = 10
            for ch_name, ch_value in continuous.items():
                label = f"{ch_name}: {ch_value:.2f}"
                cv2.putText(frame, label, (x_offset, bar_y + 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1, cv2.LINE_AA)
                bar_x = x_offset + 130
                cv2.rectangle(frame, (bar_x, bar_y), (bar_x + 60, bar_y + 8), (60, 60, 60), -1)
                cv2.rectangle(frame, (bar_x, bar_y), (bar_x + int(60 * ch_value), bar_y + 8), GREEN, -1)
                x_offset += 210
