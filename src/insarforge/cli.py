"""Command-line interface for InSARForge Phase 2."""

import argparse
import platform
import sys

from ._version import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insarforge",
        description="InSARForge command-line interface.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"insarforge {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Report Core environment status.",
        description="Report Core environment status.",
    )
    doctor_parser.set_defaults(handler=_doctor)

    config_parser = subparsers.add_parser(
        "config",
        help="Configuration commands.",
        description="Configuration commands.",
    )
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    validate_parser = config_subparsers.add_parser(
        "validate",
        help="Validate a configuration path (Phase 2 placeholder).",
        description="Validate a configuration path (Phase 2 placeholder).",
    )
    validate_parser.add_argument("path", help="Configuration file path.")
    validate_parser.set_defaults(handler=_validate_config)
    config_parser.set_defaults(config_parser=config_parser)

    return parser


def _doctor(_args: argparse.Namespace) -> int:
    print("InSARForge doctor")
    print(f"Version: {__version__}")
    print(f"Python: {platform.python_version()}")
    print("Core environment: OK")
    print("External backend checks: not implemented in Phase 2")
    return 0


def _validate_config(_args: argparse.Namespace) -> int:
    print("Configuration validation is not implemented in Phase 2.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Run the InSARForge CLI and return a process exit status."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "config" and args.config_command is None:
        args.config_parser.print_help()
        return 0

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)
