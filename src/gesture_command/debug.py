"""Debug viewer: webcam feed with hand landmarks and gesture recognition overlay."""

import cv2
import numpy as np
import time
from gesture_command.capture import Camera
from gesture_command.tracker import HandTracker, draw_landmarks
from gesture_command.recognizer import recognize, extended_fingers


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


def _draw_info_panel(frame, fps: float, hand_count: int, gesture_info: list):
    """Draw an info panel on the top-left of the frame."""
    h, w = frame.shape[:2]

    # Dark background panel (in-place, no full-frame copy)
    panel_h = max(40 + len(gesture_info) * 50, 80)
    roi = frame[0:panel_h, 0:320]
    roi[:] = (roi * 0.3 + np.array(DARK_BG) * 0.7).astype(np.uint8)

    # FPS and hand count
    cv2.putText(frame, f"FPS: {fps:.0f}", (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)
    cv2.putText(frame, f"Hands: {hand_count}", (120, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)

    # Gesture info per hand
    for i, (handedness, gesture_name, confidence, fingers) in enumerate(gesture_info):
        y_base = 50 + i * 50

        # Hand label
        cv2.putText(frame, f"{handedness}:", (10, y_base),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1, cv2.LINE_AA)

        if gesture_name:
            color = _confidence_color(confidence)
            # Gesture name
            cv2.putText(frame, gesture_name.upper(), (10, y_base + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
            # Confidence
            cv2.putText(frame, f"{confidence:.0%}", (230, y_base + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        else:
            cv2.putText(frame, "---", (10, y_base + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 1, cv2.LINE_AA)

        # Finger status dots
        finger_names = ["T", "I", "M", "R", "P"]
        finger_keys = ["thumb", "index", "middle", "ring", "pinky"]
        for j, (label, key) in enumerate(zip(finger_names, finger_keys)):
            x = 200 + j * 22
            is_ext = fingers.get(key, False)
            dot_color = GREEN if is_ext else RED
            cv2.circle(frame, (x, y_base - 5), 6, dot_color, -1, cv2.LINE_AA)
            cv2.putText(frame, label, (x - 4, y_base - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.25, WHITE, 1, cv2.LINE_AA)


def _draw_gesture_label(frame, hand, gesture_name: str, confidence: float):
    """Draw gesture label near the hand in the frame."""
    h, w = frame.shape[:2]
    # Position label above the wrist
    wrist = hand.landmarks[0]
    px = int(wrist[0] * w)
    py = int(wrist[1] * h) - 20

    color = _confidence_color(confidence)
    text = f"{gesture_name.upper()} ({confidence:.0%})"

    # Background rectangle
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (px - 5, py - th - 5), (px + tw + 5, py + 5), DARK_BG, -1)
    cv2.putText(frame, text, (px, py),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)


def run(camera_index: int = 0, detect_every: int = 2):
    """Run the debug viewer.

    detect_every: run MediaPipe every Nth frame (1 = every frame, 2 = every
    other frame). Skipped frames reuse the previous detection results so the
    video stays smooth while detection keeps up.
    """
    print("Starting GestureCommand debug viewer...")
    print("Press 'q' or ESC to quit.")
    print()

    camera = Camera(camera_index=camera_index)
    tracker = HandTracker(max_hands=2)

    prev_time = time.time()
    fps = 0.0
    frame_count = 0
    cached_hands = []
    cached_gesture_info = []

    try:
        camera.open()
        print("Camera opened. Showing debug window...")

        while True:
            frame = camera.read()
            if frame is None:
                continue

            # Flip horizontally for mirror effect
            frame = cv2.flip(frame, 1)

            # Only run detection every Nth frame
            frame_count += 1
            if frame_count % detect_every == 0:
                cached_hands = tracker.process(frame)

                cached_gesture_info = []
                for hand in cached_hands:
                    result = recognize(hand)
                    fingers = extended_fingers(hand)
                    if result:
                        cached_gesture_info.append((hand.handedness, result[0], result[1], fingers))
                    else:
                        cached_gesture_info.append((hand.handedness, None, 0.0, fingers))

            # Calculate FPS
            now = time.time()
            dt = now - prev_time
            prev_time = now
            fps = 0.9 * fps + 0.1 * (1.0 / dt if dt > 0 else 0)

            # Draw cached results on every frame
            for hand in cached_hands:
                draw_landmarks(frame, hand)
            for info in cached_gesture_info:
                handedness, gesture_name, confidence, fingers = info
                if gesture_name:
                    # Find matching hand for label position
                    for hand in cached_hands:
                        if hand.handedness == handedness:
                            _draw_gesture_label(frame, hand, gesture_name, confidence)
                            break

            _draw_info_panel(frame, fps, len(cached_hands), cached_gesture_info)

            cv2.imshow("GestureCommand Debug", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:
                break

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        camera.close()
        tracker.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run()
