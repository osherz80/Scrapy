"""CLI composition root. Collection is enabled only after its implementation gates."""

import argparse
from collections.abc import Mapping, Sequence
from uuid import UUID

from .chains import CHAINS
from .config import ConfigurationError, load_settings
from .logging import create_logger
from .logging.types import Transport


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's generated errors can echo arbitrary credential-bearing input.
        super().error("Invalid command arguments; use --help")


def _branches(value: str) -> int:
    try:
        count = int(value)
        if not 1 <= count <= 3:
            raise ValueError
        return count
    except ValueError:
        raise argparse.ArgumentTypeError("Branch count must be 1..3") from None


def _chains(value: str) -> tuple[str, ...]:
    ids = tuple(part.strip() for part in value.split(","))
    known = {chain.id for chain in CHAINS}
    if len(set(ids)) != len(ids) or any(chain not in known for chain in ids):
        raise argparse.ArgumentTypeError("Unknown or duplicate chain ID")
    return ids


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="ingestor")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check-config", help="Validate process settings without connections"
    )
    check.add_argument("--require-database", action="store_true")
    refresh = commands.add_parser("refresh", help="Reserved: refresh an authorized run")
    refresh.add_argument("--run-id", required=True, type=UUID)
    scheduled = commands.add_parser("scheduled", help="Reserved: run Israel daily scheduling")
    scheduled.add_argument("--timezone", choices=["Asia/Jerusalem"], default="Asia/Jerusalem")
    probe = commands.add_parser("probe", help="Reserved: bounded provider feasibility probe")
    probe.add_argument("--chains", type=_chains)
    probe.add_argument("--max-branches", type=_branches, default=1)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(
            env,
            require_database=args.command in ("refresh", "scheduled")
            or getattr(args, "require_database", False),
        )
        chains = getattr(args, "chains", None) or settings.enabled_chains
        if any(chain not in settings.enabled_chains for chain in chains):
            raise ConfigurationError("Requested chains must be enabled in ENABLED_CHAINS")
    except ConfigurationError as error:
        logger = create_logger(transport=transport)
        try:
            logger.error("configuration.invalid", str(error))
            return 2
        finally:
            logger.flush()
    logger = create_logger(
        level=settings.log_level,
        environment=settings.log_env,
        version=settings.app_version,
        transport=transport,
    ).child(
        entry_point=args.command,
        **({"run_id": str(args.run_id)} if args.command == "refresh" else {}),
    )
    try:
        if args.command == "check-config":
            logger.info(
                "configuration.validated", "Process configuration is valid", chain_count=len(chains)
            )
            return 0
        logger.error("command.unavailable", "Collection command is not enabled yet")
        return 3
    finally:
        logger.flush()


if __name__ == "__main__":
    raise SystemExit(main())
