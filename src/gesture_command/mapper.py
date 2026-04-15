"""Config system: load JSON config, map gestures to actions, hot-reload."""

import json
import os
import time

DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/gesture-command")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.json")
BUNDLED_DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "config", "default.json")


class Config:
    """Loads and manages gesture-to-action configuration."""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._data: dict = {}
        self._last_mtime: float = 0
        self._last_check: float = 0

    def load(self):
        """Load config from file. Creates default if missing."""
        if not os.path.exists(self.config_path):
            self._create_default()

        try:
            with open(self.config_path, "r") as f:
                self._data = json.load(f)
            self._last_mtime = os.path.getmtime(self.config_path)
            self._validate()
            print(f"Config loaded from {self.config_path}")
        except json.JSONDecodeError as e:
            print(f"[error] Invalid JSON in config: {e}")
        except Exception as e:
            print(f"[error] Failed to load config: {e}")

    def check_reload(self):
        """Check if config file changed and reload if so. Call periodically."""
        now = time.monotonic()
        if now - self._last_check < 1.0:  # check at most once per second
            return
        self._last_check = now

        try:
            mtime = os.path.getmtime(self.config_path)
            if mtime > self._last_mtime:
                print("[config] Detected change, reloading...")
                self.load()
        except OSError:
            pass

    def _create_default(self):
        """Copy bundled default config to user config dir."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        # Find bundled default relative to this file
        bundled = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "default.json")
        )
        if os.path.exists(bundled):
            import shutil
            shutil.copy2(bundled, self.config_path)
            print(f"Created default config at {self.config_path}")
        else:
            # Write minimal default inline
            default = _minimal_default()
            with open(self.config_path, "w") as f:
                json.dump(default, f, indent=2)
            print(f"Created minimal config at {self.config_path}")

    def _validate(self):
        """Basic validation of config structure."""
        if "version" not in self._data:
            print("[warning] Config missing 'version' field")
        if "gestures" not in self._data and "continuous" not in self._data:
            print("[warning] Config has no 'gestures' or 'continuous' mappings")

    # --- Accessors ---

    @property
    def settings(self) -> dict:
        return self._data.get("settings", {})

    @property
    def camera_index(self) -> int:
        return self.settings.get("camera_index", 0)

    @property
    def default_dwell_ms(self) -> float:
        return self.settings.get("default_dwell_ms", 300)

    @property
    def default_cooldown_ms(self) -> float:
        return self.settings.get("default_cooldown_ms", 500)

    @property
    def confidence_threshold(self) -> float:
        return self.settings.get("confidence_threshold", 0.7)

    @property
    def show_debug(self) -> bool:
        return self.settings.get("show_debug", True)

    @property
    def toggle_hotkey(self) -> str:
        return self.settings.get("toggle_hotkey", "cmd+shift+g")

    @property
    def start_enabled(self) -> bool:
        return self.settings.get("start_enabled", True)

    def get_gesture_action(self, gesture_name: str) -> dict | None:
        """Get the action config for a discrete gesture."""
        gestures = self._data.get("gestures", {})
        entry = gestures.get(gesture_name)
        if entry:
            return entry.get("action")
        return None

    def get_gesture_overrides(self, gesture_name: str) -> dict:
        """Get per-gesture filter overrides (dwell_ms, cooldown_ms)."""
        gestures = self._data.get("gestures", {})
        entry = gestures.get(gesture_name, {})
        overrides = {}
        if "dwell_ms" in entry:
            overrides["dwell_ms"] = entry["dwell_ms"]
        if "cooldown_ms" in entry:
            overrides["cooldown_ms"] = entry["cooldown_ms"]
        return overrides

    def get_discrete_gestures(self) -> dict:
        """Get all discrete gesture mappings."""
        return self._data.get("gestures", {})

    def get_continuous_mappings(self) -> dict:
        """Get all continuous gesture-to-action mappings."""
        return self._data.get("continuous", {})

    @property
    def raw(self) -> dict:
        return dict(self._data)


def _minimal_default() -> dict:
    return {
        "version": 1,
        "settings": {
            "camera_index": 0,
            "default_dwell_ms": 300,
            "default_cooldown_ms": 500,
            "confidence_threshold": 0.7,
            "show_debug": True,
            "toggle_hotkey": "cmd+shift+g",
            "start_enabled": True
        },
        "gestures": {
            "open_palm": {
                "action": {"type": "keypress", "keys": "space"}
            },
            "fist": {
                "action": {"type": "keypress", "keys": "cmd+w"},
                "dwell_ms": 400,
                "cooldown_ms": 800
            },
            "thumbs_up": {
                "action": {"type": "shell", "command": "open -a 'Finder'"}
            },
            "peace": {
                "action": {"type": "keypress", "keys": "cmd+tab"}
            },
            "point": {
                "action": {"type": "mouse_click", "button": "left"}
            }
        },
        "continuous": {
            "pinch_distance:left": {
                "action": {"type": "brightness"},
                "smoothing": 0.3,
                "dead_zone": 0.03,
                "update_interval_ms": 200,
                "activation_ms": 800,
                "invert": False
            },
            "pinch_distance:right": {
                "action": {"type": "volume"},
                "smoothing": 0.3,
                "dead_zone": 0.03,
                "update_interval_ms": 200,
                "activation_ms": 800,
                "invert": False
            }
        }
    }
