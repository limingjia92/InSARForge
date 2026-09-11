"""Lightweight command registration for InSARForge."""

import argparse
import platform

from ._version import __version__


class SafeArgumentParser(argparse.ArgumentParser):
    """Argparse syntax diagnostics must not echo arbitrary tokens or values."""

    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        self.print_usage(__import__("sys").stderr)
        detail = (
            "required: path"
            if message == "the following arguments are required: path"
            else "invalid command-line arguments"
        )
        self.exit(2, f"{self.prog}: error: {detail}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
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
        "validate", help="Validate configuration."
    )
    validate_parser.add_argument("path", help="Configuration file path.")
    validate_parser.add_argument(
        "--set", dest="set_values", action="append", default=[]
    )
    validate_parser.set_defaults(handler=_validate_config)
    resolve_parser = config_subparsers.add_parser(
        "resolve", help="Resolve configuration defaults."
    )
    resolve_parser.add_argument("path", help="Configuration file path.")
    resolve_parser.add_argument("--set", dest="set_values", action="append", default=[])
    resolve_parser.add_argument("--explain", action="store_true")
    resolve_parser.add_argument("--write-dir")
    resolve_parser.set_defaults(handler=_resolve_config)
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
    from .config.cli import run_validate

    return run_validate(_args.path, _args.set_values)


def _resolve_config(args: argparse.Namespace) -> int:
    from .config.cli import run_resolve

    return run_resolve(args.path, args.set_values, args.explain, args.write_dir)


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
