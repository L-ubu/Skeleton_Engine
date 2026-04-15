import math
from gesture_command.tracker import Hand

# MediaPipe hand landmark indices
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

FINGERS = {
    "thumb": (THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP),
    "index": (INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
    "middle": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
    "ring": (RING_MCP, RING_PIP, RING_DIP, RING_TIP),
    "pinky": (PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
}

# Ordered list for iteration (excluding thumb which has special logic)
FINGER_NAMES = ["index", "middle", "ring", "pinky"]


# --- Primitives ---

def _dist(a: tuple, b: tuple) -> float:
    """Euclidean distance between two (x, y, z) landmarks."""
    return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2 + (a[2] - b[2])**2)


def _dist_2d(a: tuple, b: tuple) -> float:
    """Euclidean distance in x,y only."""
    return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)


def _angle(a: tuple, b: tuple, c: tuple) -> float:
    """Angle at point b formed by points a-b-c, in degrees."""
    ba = (a[0] - b[0], a[1] - b[1], a[2] - b[2])
    bc = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
    dot = ba[0]*bc[0] + ba[1]*bc[1] + ba[2]*bc[2]
    mag_ba = math.sqrt(ba[0]**2 + ba[1]**2 + ba[2]**2)
    mag_bc = math.sqrt(bc[0]**2 + bc[1]**2 + bc[2]**2)
    if mag_ba * mag_bc == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ba * mag_bc)))
    return math.degrees(math.acos(cos_angle))


def is_finger_extended(hand: Hand, finger: str) -> bool:
    """Check if a finger is extended (straight-ish)."""
    lm = hand.landmarks
    if finger == "thumb":
        # Thumb: compare tip distance from wrist vs IP distance from wrist
        # More reliable than y-comparison for thumb
        tip_dist = _dist_2d(lm[THUMB_TIP], lm[WRIST])
        ip_dist = _dist_2d(lm[THUMB_IP], lm[WRIST])
        return tip_dist > ip_dist
    else:
        mcp, pip, dip, tip = FINGERS[finger]
        # Finger is extended if tip is farther from wrist than PIP joint
        # Using y-axis: tip.y < pip.y means extended (y increases downward)
        # But we also check angle to be more robust
        angle = _angle(lm[mcp], lm[pip], lm[tip])
        return angle > 140  # relatively straight


def finger_curl_angle(hand: Hand, finger: str) -> float:
    """Get the curl angle of a finger (0 = fully extended, 180 = fully curled)."""
    lm = hand.landmarks
    if finger == "thumb":
        return 180 - _angle(lm[THUMB_CMC], lm[THUMB_MCP], lm[THUMB_TIP])
    mcp, pip, dip, tip = FINGERS[finger]
    return 180 - _angle(lm[mcp], lm[pip], lm[tip])


def pinch_distance(hand: Hand) -> float:
    """Distance between thumb tip and index tip (normalized)."""
    return _dist(hand.landmarks[THUMB_TIP], hand.landmarks[INDEX_TIP])


def extended_fingers(hand: Hand) -> dict[str, bool]:
    """Get extension state of all fingers."""
    return {
        "thumb": is_finger_extended(hand, "thumb"),
        "index": is_finger_extended(hand, "index"),
        "middle": is_finger_extended(hand, "middle"),
        "ring": is_finger_extended(hand, "ring"),
        "pinky": is_finger_extended(hand, "pinky"),
    }


# --- Gesture Detectors ---

def _detect_fist(hand: Hand) -> float:
    """All fingers curled."""
    ext = extended_fingers(hand)
    curled_count = sum(1 for v in ext.values() if not v)
    if curled_count == 5:
        return 0.95
    if curled_count == 4 and not ext["thumb"]:
        # Thumb can be ambiguous, 4 fingers curled + thumb curled is still a fist
        return 0.85
    return 0.0


def _detect_open_palm(hand: Hand) -> float:
    """All fingers extended."""
    ext = extended_fingers(hand)
    extended_count = sum(1 for v in ext.values() if v)
    if extended_count == 5:
        return 0.95
    if extended_count == 4:
        return 0.6
    return 0.0


def _detect_thumbs_up(hand: Hand) -> float:
    """Only thumb extended, hand roughly upright."""
    ext = extended_fingers(hand)
    if not ext["thumb"]:
        return 0.0
    others_curled = not any(ext[f] for f in FINGER_NAMES)
    if not others_curled:
        return 0.0
    # Check thumb is pointing up: thumb tip should be above thumb CMC
    lm = hand.landmarks
    if lm[THUMB_TIP][1] < lm[THUMB_CMC][1]:  # y increases downward
        return 0.9
    return 0.4  # thumb extended but not pointing up


def _detect_peace(hand: Hand) -> float:
    """Index + middle extended, rest curled."""
    ext = extended_fingers(hand)
    if ext["index"] and ext["middle"] and not ext["ring"] and not ext["pinky"]:
        return 0.9
    return 0.0


def _detect_point(hand: Hand) -> float:
    """Only index finger extended."""
    ext = extended_fingers(hand)
    if ext["index"] and not ext["middle"] and not ext["ring"] and not ext["pinky"]:
        return 0.9
    return 0.0


def _detect_pinch(hand: Hand) -> float:
    """Thumb tip close to index tip."""
    dist = pinch_distance(hand)
    if dist < 0.05:
        return 0.95
    if dist < 0.08:
        return 0.7
    return 0.0


def _detect_three(hand: Hand) -> float:
    """Index + middle + ring extended, pinky curled."""
    ext = extended_fingers(hand)
    if ext["index"] and ext["middle"] and ext["ring"] and not ext["pinky"]:
        return 0.9
    return 0.0


def _detect_rock(hand: Hand) -> float:
    """Index + pinky extended, middle + ring curled."""
    ext = extended_fingers(hand)
    if ext["index"] and ext["pinky"] and not ext["middle"] and not ext["ring"]:
        return 0.9
    return 0.0


# Registry of all gesture detectors
GESTURE_DETECTORS = {
    "fist": _detect_fist,
    "open_palm": _detect_open_palm,
    "thumbs_up": _detect_thumbs_up,
    "peace": _detect_peace,
    "point": _detect_point,
    "pinch": _detect_pinch,
    "three_fingers": _detect_three,
    "rock": _detect_rock,
}


def recognize(hand: Hand, threshold: float = 0.6) -> tuple[str, float] | None:
    """Run all detectors, return (gesture_name, confidence) for best match above threshold."""
    best_name = None
    best_conf = 0.0

    for name, detector in GESTURE_DETECTORS.items():
        conf = detector(hand)
        if conf > best_conf:
            best_conf = conf
            best_name = name

    if best_conf >= threshold and best_name is not None:
        return (best_name, best_conf)
    return None
