# GestureCommand - Implementation Plan

A macOS tool that maps hand gestures (via webcam) to keypresses, mouse actions, shell commands, and multi-step macros. Config-driven via JSON, controlled via CLI.

**Stack:** Python 3.11+ | MediaPipe | OpenCV | pynput

---

## Phase 1: Camera + Hand Tracking (foundation)

> Get MediaPipe hand landmarks streaming from the webcam in real-time with a debug overlay.

### Chunk 1A: Project scaffolding
- Create `pyproject.toml` with dependencies: `mediapipe`, `opencv-python`, `pynput`
- Set up `src/gesture_command/` package structure
- Create virtual environment, install deps

### Chunk 1B: Webcam capture module
- `src/gesture_command/capture.py`
- Open webcam via OpenCV, yield frames at 30fps
- Handle camera not found, permission denied (macOS camera permission)
- Clean shutdown on Ctrl+C

### Chunk 1C: Hand tracker module
- `src/gesture_command/tracker.py`
- Wrap MediaPipe Hand Landmarker
- Input: BGR frame from OpenCV
- Output: list of detected hands, each with 21 landmarks (normalized x,y,z), handedness (left/right), confidence score
- Draw landmarks on frame for debug visualization

### Chunk 1D: Integration - debug viewer
- `src/gesture_command/debug.py`
- Combine capture + tracker: show webcam feed with hand landmarks drawn on screen
- Display FPS counter, hand count, landmark positions
- Run as: `python -m gesture_command.debug`
- **Milestone: see your hand landmarks moving in real-time**

---

## Phase 2: Gesture Recognition (rule-based)

> Detect specific hand gestures from the landmark data.

### Chunk 2A: Gesture primitives
- `src/gesture_command/recognizer.py`
- Utility functions on landmarks:
  - `is_finger_extended(landmarks, finger)` - compare tip y vs PIP joint y (adjusted for hand orientation)
  - `finger_curl_angle(landmarks, finger)` - angle between MCP-PIP-TIP
  - `distance(landmark_a, landmark_b)` - euclidean distance between two points
  - `palm_velocity(current, previous)` - movement speed of palm center between frames

### Chunk 2B: Built-in gesture detectors
- Implement these starter gestures using the primitives:
  1. **Fist** - all fingers curled
  2. **Open palm** - all fingers extended
  3. **Thumbs up** - only thumb extended, hand roughly upright
  4. **Peace / Victory** - index + middle extended, rest curled
  5. **Point** - only index finger extended
  6. **Pinch** - thumb tip close to index tip (distance threshold)
  7. **Three fingers** - index + middle + ring extended
  8. **Rock / horns** - index + pinky extended, middle + ring curled
- Each detector returns: `(gesture_name, confidence: float)`
- A `recognize(landmarks)` function that runs all detectors, returns highest-confidence match above threshold

### Chunk 2C: Continuous gesture recognizers
- `src/gesture_command/continuous.py`
- Unlike discrete gestures (fire once), these output a **float value every frame** mapped to a 0.0-1.0 range
- Built-in continuous gestures:
  1. **Pinch distance** - distance between thumb tip and index tip, normalized to 0.0 (closed) - 1.0 (spread). Requires pinch posture detected first (other fingers curled) to avoid false reads during normal hand movement
  2. **Hand rotation** - angle of the hand around the wrist axis (roll). 0.0 = palm down, 0.5 = palm sideways, 1.0 = palm up. Calculated from wrist-to-middle-finger-MCP vector vs horizontal
  3. **Palm height** - vertical position of palm center in frame, normalized. 0.0 = bottom of frame, 1.0 = top
  4. **Hand spread** - average distance between all fingertips, normalized. Fist = 0.0, fully spread = 1.0
  5. **Fist squeeze** - average finger curl angle, normalized. Open = 0.0, tight fist = 1.0
- Each outputs: `(channel_name, value: float, active: bool)` - `active` is False when the hand pose doesn't match the activation condition (e.g., pinch distance only active when in pinch posture)
- Smoothing: apply exponential moving average to raw values to prevent jitter (configurable smoothing factor)
- Dead zone: ignore values that change less than a configurable threshold between frames

### Chunk 2D: Debug overlay update
- Show detected gesture name on the debug viewer
- Color-code confidence (green = high, yellow = medium, red = low)
- For continuous gestures: show a live value bar next to the hand (e.g., a small horizontal bar that fills based on pinch distance)
- Show channel name + numeric value when a continuous gesture is active
- **Milestone: point at camera, see "POINT" on screen. Pinch and spread fingers, see the value bar move smoothly.**

---

## Phase 3: Gesture Filtering (anti-false-trigger)

> Prevent accidental triggers and make recognition feel solid.

### Chunk 3A: Filter pipeline
- `src/gesture_command/filters.py`
- **Dwell time**: gesture must be held for N ms before it "fires" (default: 300ms)
- **Cooldown**: after a gesture fires, ignore that same gesture for N ms (default: 500ms)
- **Confidence threshold**: ignore recognitions below threshold (default: 0.7)
- **Debounce**: require gesture to be stable for N consecutive frames
- All thresholds configurable per-gesture in the JSON config

### Chunk 3B: State machine
- Track gesture state: `idle` -> `detecting` (dwell counting) -> `fired` -> `cooldown` -> `idle`
- Emit events: `gesture_started`, `gesture_fired`, `gesture_ended`
- Show state in debug viewer (e.g., dwell progress bar)
- **Milestone: gestures feel intentional, not twitchy**

---

## Phase 4: Action Execution

> Turn fired gestures into OS-level actions.

### Chunk 4A: Discrete action types
- `src/gesture_command/actions.py`
- **Keypress**: single key or combo (`cmd+c`, `ctrl+shift+a`, `space`, `f5`)
- **Mouse click**: left/right/middle click at current position
- **Mouse move**: move cursor by relative x,y offset
- **Shell command**: run arbitrary shell command via subprocess (non-blocking)
- **Macro**: ordered sequence of the above actions with configurable delays between steps

### Chunk 4A2: Continuous action types
- `src/gesture_command/continuous_actions.py`
- **Volume**: set macOS system volume (0-100) via `osascript -e "set volume output volume {value}"`
- **Brightness**: set screen brightness via `brightness` CLI tool or CoreDisplay private framework
- **Scroll**: emit scroll events via pynput at a rate proportional to the value (0 = no scroll, 1 = fast scroll). Direction configurable (up/down)
- **Zoom**: emit cmd+plus / cmd+minus keypresses at a rate proportional to value change, or pinch-to-zoom trackpad events
- **Mouse speed**: move mouse cursor at a speed proportional to value (for palm-height-to-cursor-speed mapping)
- **Custom AppleScript**: run arbitrary AppleScript with `{value}` placeholder replaced by current float value
- All continuous actions receive a 0.0-1.0 float every frame and translate it to the appropriate OS call
- Rate limiting: don't fire OS calls every frame - use a configurable update interval (default: 50ms) and only fire when value has changed meaningfully

### Chunk 4B: Action executor
- Parse action definitions from config format
- Execute discrete actions safely:
  - Keypresses via pynput `Controller`
  - Mouse via pynput `mouse.Controller`
  - Shell commands via `subprocess.Popen` (non-blocking, with timeout)
  - Macros: sequential execution with `time.sleep()` between steps
- Execute continuous actions:
  - Receive `(channel_name, value)` pairs each frame
  - Route to the appropriate continuous action handler
  - Respect rate limiting and minimum-change thresholds
- Handle macOS accessibility permissions for pynput (needs to be enabled in System Settings > Privacy & Security > Accessibility)

---

## Phase 5: Config System + Action Mapping

> Connect gestures to actions via a JSON config file.

### Chunk 5A: Config schema and loader
- `src/gesture_command/mapper.py`
- JSON config format:

```json
{
  "version": 1,
  "settings": {
    "camera_index": 0,
    "default_dwell_ms": 300,
    "default_cooldown_ms": 500,
    "confidence_threshold": 0.7,
    "show_debug": true,
    "toggle_hotkey": "cmd+shift+g",
    "start_enabled": true
  },
  "gestures": {
    "fist": {
      "action": { "type": "keypress", "keys": "cmd+w" },
      "dwell_ms": 400,
      "cooldown_ms": 800
    },
    "open_palm": {
      "action": { "type": "keypress", "keys": "space" }
    },
    "thumbs_up": {
      "action": {
        "type": "macro",
        "steps": [
          { "type": "keypress", "keys": "cmd+a" },
          { "delay_ms": 100 },
          { "type": "keypress", "keys": "cmd+c" }
        ]
      }
    },
    "pinch": {
      "action": { "type": "shell", "command": "open -a 'Spotify'" }
    },
    "point": {
      "action": { "type": "mouse_click", "button": "left" }
    }
  },
  "continuous": {
    "pinch_distance": {
      "action": { "type": "volume" },
      "smoothing": 0.3,
      "dead_zone": 0.02,
      "update_interval_ms": 50,
      "invert": false
    },
    "hand_rotation": {
      "action": { "type": "scroll", "direction": "vertical" },
      "smoothing": 0.4,
      "dead_zone": 0.05
    },
    "palm_height": {
      "action": { "type": "brightness" },
      "smoothing": 0.3,
      "dead_zone": 0.03
    },
    "hand_spread": {
      "action": { "type": "zoom" },
      "smoothing": 0.3,
      "dead_zone": 0.04
    }
  }
}
```

- Hot-reload: watch config file for changes, reload without restart (via file mtime polling)
- Validate config on load, print clear errors for invalid entries

### Chunk 5B: Default config
- `config/default.json` with sensible starter mappings
- Copy to `~/.config/gesture-command/config.json` on first run

---

## Phase 6: Main Engine + CLI

> Tie everything together into a runnable tool.

### Chunk 6A: Engine loop
- `src/gesture_command/engine.py`
- Main loop: capture frame -> track hands -> recognize gesture -> filter -> map to action -> execute
- Two parallel pipelines in the loop:
  - Discrete: recognize -> filter (dwell/cooldown) -> fire action once
  - Continuous: read channels -> smooth -> map to continuous action every N ms
- Threading: camera capture on one thread, processing on main thread
- Clean shutdown on SIGINT/SIGTERM
- Optional debug window (toggleable via config or CLI flag)
- **Global hotkey toggle**: register a system-wide keyboard shortcut (configurable, default: `cmd+shift+g`) via pynput hotkey listener to instantly enable/disable gesture recognition. When disabled, camera keeps running (for debug view) but no gestures fire. Visual indicator on debug overlay (green = active, red = paused). Also show a macOS notification on toggle so you know the state even without the debug window

### Chunk 6B: CLI interface
- `src/gesture_command/cli.py` using `argparse` (or `click` if we want nicer UX)
- Commands:
  - `gesture-command start` - start the engine (foreground, with optional `--debug` flag for overlay window)
  - `gesture-command stop` - stop a running background instance
  - `gesture-command list-gestures` - show all recognized gestures
  - `gesture-command config` - print current config path and validate it
  - `gesture-command config --edit` - open config in $EDITOR
- Entry point in `pyproject.toml`: `[project.scripts] gesture-command = "gesture_command.cli:main"`

### Chunk 6C: First full integration test (manual)
- **Milestone: run `gesture-command start --debug`, see camera feed, make gestures, watch keypresses/actions fire**

---

## Phase 7: Polish + Quality of Life

> Make it actually pleasant to use.

### Chunk 7A: Logging and feedback
- Console output showing fired gestures and actions in real-time
- Optional notification (macOS notification center) when gesture fires
- Colored terminal output for gesture events

### Chunk 7B: macOS integration
- Handle camera permission prompts gracefully
- Handle accessibility permission for pynput (detect if missing, print instructions)
- Launch agent support for running in background (`launchd` plist)

### Chunk 7C: Gesture calibration helper
- `gesture-command calibrate` - interactive mode where you hold each gesture and the tool shows what it detects + confidence
- Helps users understand what gestures look like to the system
- Shows which fingers the system thinks are extended/curled

---

## Future Phases (not in scope for v1)

- **Face tracking**: MediaPipe Face Landmarker, map expressions (wink, raise eyebrows, mouth open) to actions
- **Body pose**: MediaPipe Pose, map body positions to actions
- **Dynamic gestures**: swipe, circle, wave - requires temporal tracking with DTW or LSTM
- **GUI config app**: web or native UI for mapping gestures to actions visually
- **Custom gesture training**: record your own gestures, train a classifier
- **Per-app profiles**: different gesture mappings depending on the active application
- **Finger mouse mode**: index finger controls cursor position (mapped to screen coordinates), index finger tap-down = left click, middle finger tap-down = right click. Essentially turns your hand into a trackpad in the air
- **Gesture combos**: two-gesture sequences (like key chords)

---

## Build Order Summary

| Phase | What | Depends On | Parallel? |
|-------|------|------------|-----------|
| 1A | Project scaffolding | nothing | - |
| 1B | Webcam capture | 1A | can parallel with 1C |
| 1C | Hand tracker | 1A | can parallel with 1B |
| 1D | Debug viewer | 1B + 1C | - |
| 2A | Gesture primitives | 1C | - |
| 2B | Discrete gesture detectors | 2A | - |
| 2C | Continuous gesture recognizers | 2A | can parallel with 2B |
| 2D | Debug overlay update | 1D + 2B + 2C | - |
| 3A | Filter pipeline | 2B | - |
| 3B | State machine | 3A | - |
| 4A | Discrete action types | 1A | can parallel with Phase 2-3 |
| 4A2 | Continuous action types | 1A | can parallel with 4A |
| 4B | Action executor | 4A + 4A2 | - |
| 5A | Config loader | 4B + 3B | - |
| 5B | Default config | 5A | - |
| 6A | Engine loop + toggle hotkey | 5A + 5B | - |
| 6B | CLI | 6A | - |
| 6C | Full integration | 6B | - |
| 7A-C | Polish | 6C | all parallel |
