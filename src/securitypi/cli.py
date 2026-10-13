"""CLI: validate configuration or start the localhost foundation API."""

import argparse
import logging
import sys
from pathlib import Path

from securitypi import __version__
from securitypi.config import ConfigError, load_settings
from securitypi.logging import configure_logging, logging_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SecurityPI local security service")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("check-config", "serve"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", type=Path, required=True, help="Non-secret TOML file")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"securitypi: {exc}", file=sys.stderr)
        return 2

    configure_logging(settings.log_level)
    logger = logging.getLogger("securitypi")
    if args.command == "check-config":
        logger.info("Configuration valid. No hardware or network connections started.")
        return 0

    import uvicorn

    from securitypi.api import create_app

    logger.info("Starting foundation API. Camera monitoring is not implemented yet.")
    uvicorn.run(
        create_app(settings),
        host=settings.server.host,
        port=settings.server.port,
        log_config=logging_config(settings.log_level),
        access_log=False,
    )
    return 0
