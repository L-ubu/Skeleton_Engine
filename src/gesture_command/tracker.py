import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import numpy as np
import os
import urllib.request

# MediaPipe hand landmark indices for drawing connections
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),       # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),       # index
    (0, 9), (9, 10), (10, 11), (11, 12),   # middle
    (0, 13), (13, 14), (14, 15), (15, 16), # ring
    (0, 17), (17, 18), (18, 19), (19, 20), # pinky
    (5, 9), (9, 13), (13, 17),             # palm
]

# Color scheme for drawing
JOINT_COLORS = {
    "wrist": (0, 69, 233),      # red-ish (BGR)
    "thumb": (157, 107, 255),    # pink
    "mcp": (136, 255, 0),        # green
    "finger": (255, 99, 108),    # blue-purple
    "tip": (255, 99, 108),       # blue-purple
}

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "hand_landmarker.task")


def _ensure_model():
    """Download the hand landmarker model if not present."""
    if os.path.exists(MODEL_PATH):
        return
    os.makedirs(MODEL_DIR, exist_ok=True)
    print(f"Downloading hand landmarker model...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Model downloaded.")


class Hand:
    """Represents a single detected hand."""

    def __init__(self, landmarks, handedness: str, confidence: float):
        self.landmarks = landmarks  # list of 21 (x, y, z) normalized
        self.handedness = handedness
        self.confidence = confidence

    def landmark(self, index: int):
        """Get (x, y, z) for a landmark by index."""
        return self.landmarks[index]


class HandTracker:
    """Wraps MediaPipe Hand Landmarker in synchronous VIDEO mode.

    Skeleton stays perfectly in sync with the video frame at the cost of
    blocking until detection finishes.  Half-res processing keeps it fast.
    """

    def __init__(self, max_hands: int = 2, min_confidence: float = 0.5):
        _ensure_model()
        self._frame_ts = 0
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=min_confidence,
            min_hand_presence_confidence=min_confidence,
            min_tracking_confidence=min_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def process(self, bgr_frame) -> list[Hand]:
        """Process a BGR frame and return detected hands (synchronous)."""
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        self._frame_ts += 33
        result = self._landmarker.detect_for_video(mp_image, self._frame_ts)

        hands = []
        for i, hand_landmarks in enumerate(result.hand_landmarks):
            landmarks = [(lm.x, lm.y, lm.z) for lm in hand_landmarks]
            handedness = result.handedness[i][0].category_name
            confidence = result.handedness[i][0].score
            hands.append(Hand(landmarks, handedness, confidence))
        return hands

    def close(self):
        self._landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def draw_landmarks(frame, hand: Hand, alpha: float = 0.8):
    """Draw hand landmarks and connections on a frame."""
    h, w = frame.shape[:2]

    # Draw connections
    for start_idx, end_idx in HAND_CONNECTIONS:
        x1 = int(hand.landmarks[start_idx][0] * w)
        y1 = int(hand.landmarks[start_idx][1] * h)
        x2 = int(hand.landmarks[end_idx][0] * w)
        y2 = int(hand.landmarks[end_idx][1] * h)

        # Color based on finger
        if start_idx <= 4 or end_idx <= 4:
            color = JOINT_COLORS["thumb"]
        elif start_idx in (5, 9, 13, 17) and end_idx in (5, 9, 13, 17):
            color = JOINT_COLORS["mcp"]
        else:
            color = JOINT_COLORS["finger"]

        cv2.line(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

    # Draw joints
    for i, (x, y, z) in enumerate(hand.landmarks):
        px, py = int(x * w), int(y * h)
        if i == 0:
            color = JOINT_COLORS["wrist"]
            radius = 6
        elif i in (4, 8, 12, 16, 20):  # fingertips
            color = JOINT_COLORS["tip"]
            radius = 5
        elif i in (5, 9, 13, 17):  # MCP / knuckles
            color = JOINT_COLORS["mcp"]
            radius = 4
        elif i <= 4:
            color = JOINT_COLORS["thumb"]
            radius = 3
        else:
            color = JOINT_COLORS["finger"]
            radius = 3

        cv2.circle(frame, (px, py), radius, color, -1, cv2.LINE_AA)
        cv2.circle(frame, (px, py), radius, (255, 255, 255), 1, cv2.LINE_AA)
