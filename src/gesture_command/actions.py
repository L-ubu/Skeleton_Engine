"""Discrete action execution: keypresses, mouse, shell commands, macros."""

import subprocess
import time
from pynput.keyboard import Controller as KeyboardController, Key, KeyCode
from pynput.mouse import Controller as MouseController, Button


_keyboard = KeyboardController()
_mouse = MouseController()

# Map string names to pynput Key objects
_SPECIAL_KEYS = {
    "cmd": Key.cmd, "command": Key.cmd, "super": Key.cmd,
    "ctrl": Key.ctrl, "control": Key.ctrl,
    "alt": Key.alt, "option": Key.alt,
    "shift": Key.shift,
    "tab": Key.tab,
    "enter": Key.enter, "return": Key.enter,
    "space": Key.space,
    "backspace": Key.backspace, "delete": Key.backspace,
    "escape": Key.esc, "esc": Key.esc,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end,
    "pageup": Key.page_up, "pagedown": Key.page_down,
    "capslock": Key.caps_lock,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}

_MOUSE_BUTTONS = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
}


def _parse_key(key_str: str):
    """Parse a key string into a pynput Key or KeyCode."""
    lower = key_str.lower().strip()
    if lower in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[lower]
    if len(key_str) == 1:
        return KeyCode.from_char(key_str)
    raise ValueError(f"Unknown key: {key_str!r}")


def execute_keypress(keys: str):
    """Execute a keypress or key combination like 'cmd+c' or 'ctrl+shift+a'."""
    parts = [p.strip() for p in keys.split("+")]
    parsed = [_parse_key(p) for p in parts]

    if len(parsed) == 1:
        _keyboard.press(parsed[0])
        _keyboard.release(parsed[0])
    else:
        # Hold modifiers, press last key, release all
        modifiers = parsed[:-1]
        final_key = parsed[-1]
        for mod in modifiers:
            _keyboard.press(mod)
        _keyboard.press(final_key)
        _keyboard.release(final_key)
        for mod in reversed(modifiers):
            _keyboard.release(mod)


def execute_mouse_click(button: str = "left"):
    """Click a mouse button at current position."""
    btn = _MOUSE_BUTTONS.get(button.lower(), Button.left)
    _mouse.click(btn)


def execute_mouse_move(dx: int = 0, dy: int = 0):
    """Move mouse by relative offset."""
    _mouse.move(dx, dy)


def execute_shell(command: str, timeout: float = 10.0):
    """Run a shell command (non-blocking by default)."""
    subprocess.Popen(command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def execute_action(action: dict):
    """Execute a single action from config format.

    Supported types:
        {"type": "keypress", "keys": "cmd+c"}
        {"type": "mouse_click", "button": "left"}
        {"type": "mouse_move", "dx": 10, "dy": -5}
        {"type": "shell", "command": "open -a Spotify"}
        {"type": "macro", "steps": [...]}
    """
    action_type = action.get("type")

    if action_type == "keypress":
        execute_keypress(action["keys"])

    elif action_type == "mouse_click":
        execute_mouse_click(action.get("button", "left"))

    elif action_type == "mouse_move":
        execute_mouse_move(action.get("dx", 0), action.get("dy", 0))

    elif action_type == "shell":
        execute_shell(action["command"], action.get("timeout", 10.0))

    elif action_type == "macro":
        _execute_macro(action["steps"])

    else:
        print(f"[warning] Unknown action type: {action_type}")


def _execute_macro(steps: list[dict]):
    """Execute a sequence of actions with optional delays."""
    for step in steps:
        if "delay_ms" in step and "type" not in step:
            time.sleep(step["delay_ms"] / 1000.0)
        else:
            execute_action(step)
