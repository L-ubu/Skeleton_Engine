"""CLI interface for GestureCommand."""

import argparse
import sys
import os

from gesture_command.mapper import Config, DEFAULT_CONFIG_PATH
from gesture_command.recognizer import GESTURE_DETECTORS
from gesture_command.continuous import CONTINUOUS_GESTURES


def cmd_start(args):
    """Start the gesture recognition engine."""
    config = Config(config_path=args.config)
    config.load()

    if args.debug is not None:
        # CLI flag overrides config
        debug = args.debug
    else:
        debug = config.show_debug

    # Parse active gestures
    active_gestures = None
    if args.gestures:
        active_gestures = [g.strip() for g in args.gestures.split(",")]

    from gesture_command.engine import Engine
    engine = Engine(
        config, debug=debug, detect_every=args.detect_every,
        active_gestures=active_gestures, mouse_mode=args.mouse,
    )
    engine.run()


def cmd_list_gestures(args):
    """List all available gestures."""
    print("Discrete gestures (fire once when held):")
    print("-" * 40)
    for name in sorted(GESTURE_DETECTORS.keys()):
        print(f"  {name}")

    print()
    print("Continuous gestures (output 0.0-1.0 value):")
    print("-" * 40)
    for name in sorted(CONTINUOUS_GESTURES.keys()):
        print(f"  {name}")


def cmd_config(args):
    """Show or edit config."""
    config_path = args.config or DEFAULT_CONFIG_PATH

    if args.edit:
        editor = os.environ.get("EDITOR", "nano")
        os.execvp(editor, [editor, config_path])
    elif args.validate:
        config = Config(config_path=config_path)
        config.load()
        print(f"Config at: {config_path}")
        print(f"Discrete gestures mapped: {len(config.get_discrete_gestures())}")
        print(f"Continuous channels mapped: {len(config.get_continuous_mappings())}")
        print("Config is valid.")
    else:
        print(f"Config path: {config_path}")
        if os.path.exists(config_path):
            print("Status: exists")
            config = Config(config_path=config_path)
            config.load()
            print(f"Discrete gestures: {', '.join(config.get_discrete_gestures().keys()) or 'none'}")
            continuous = config.get_continuous_mappings()
            print(f"Continuous channels: {', '.join(continuous.keys()) or 'none'}")
            print(f"Toggle hotkey: {config.toggle_hotkey}")
        else:
            print("Status: not found (will be created on first run)")


def cmd_calibrate(args):
    """Run calibration mode - show what the system detects for each gesture."""
    print("GestureCommand Calibration Mode")
    print("=" * 40)
    print("Hold each gesture in front of the camera.")
    print("The system will show what it detects and the confidence level.")
    print("Press 'q' or ESC to quit.")
    print()

    # Reuse debug viewer for calibration
    from gesture_command.debug import run
    run(camera_index=args.camera or 0)


def main():
    parser = argparse.ArgumentParser(
        prog="gesture-command",
        description="Map hand gestures to keypresses, mouse actions, shell commands, and macros.",
    )
    parser.add_argument("--config", "-c", help="Path to config file", default=None)

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start
    p_start = subparsers.add_parser("start", help="Start gesture recognition engine")
    p_start.add_argument("--debug", dest="debug", action="store_true", default=None,
                         help="Show debug overlay window")
    p_start.add_argument("--no-debug", dest="debug", action="store_false",
                         help="Run without debug window")
    p_start.add_argument("--detect-every", type=int, default=2,
                         help="Run detection every Nth frame (default: 2)")
    p_start.add_argument("--gestures", "-g", type=str, default=None,
                         help="Comma-separated list of gestures to enable (e.g. 'open_palm,fist'). Others are ignored.")
    p_start.add_argument("--mouse", action="store_true", default=False,
                         help="Enable mouse mode: index finger controls cursor, tap to click")
    p_start.set_defaults(func=cmd_start)

    # list-gestures
    p_list = subparsers.add_parser("list-gestures", help="List all available gestures")
    p_list.set_defaults(func=cmd_list_gestures)

    # config
    p_config = subparsers.add_parser("config", help="Show or edit configuration")
    p_config.add_argument("--edit", action="store_true", help="Open config in $EDITOR")
    p_config.add_argument("--validate", action="store_true", help="Validate config file")
    p_config.set_defaults(func=cmd_config)

    # calibrate
    p_cal = subparsers.add_parser("calibrate", help="Run gesture calibration mode")
    p_cal.add_argument("--camera", type=int, default=0, help="Camera index")
    p_cal.set_defaults(func=cmd_calibrate)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
