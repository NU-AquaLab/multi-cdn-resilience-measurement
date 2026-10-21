"""Command-line entry point for TikTok collection and fallback measurements."""

import argparse
import importlib
import logging
from collections.abc import Sequence

from measure_tiktok.config import load_config, validate_configuration

COMMANDS = {
    "collect-vod": (
        "measure_tiktok.workflows.vod",
        "Collect video-on-demand CDN metadata",
    ),
    "collect-live": (
        "measure_tiktok.workflows.live",
        "Collect live-stream CDN metadata",
    ),
    "fallback-live": (
        "measure_tiktok.fallback.live",
        "Measure live-stream CDN fallback",
    ),
    "fallback-vod": (
        "measure_tiktok.fallback.vod",
        "Measure video-on-demand CDN fallback",
    ),
    "fallback-iterative": (
        "measure_tiktok.fallback.iterative",
        "Repeat video-on-demand fallback trials",
    ),
}


def build_parser() -> argparse.ArgumentParser:
    """Build help without importing browser, database, or measurement modules."""
    parser = argparse.ArgumentParser(
        prog="measure-tiktok",
        description="Collect TikTok CDN metadata and measure fallback behavior.",
    )
    parser.add_argument("--config", metavar="PATH", help=".env file (default: ./.env)")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="console logging level (default: INFO)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, (_, description) in COMMANDS.items():
        subparsers.add_parser(name, help=description, description=description)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Load run configuration, then dispatch the selected measurement."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        load_config(args.config)
        validate_configuration(args.command)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    module = importlib.import_module(COMMANDS[args.command][0])
    try:
        module.main()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Measurement interrupted")
        return 130
    return 0
