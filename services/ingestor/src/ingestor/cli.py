"""CLI composition root. Collection is enabled only after its implementation gates."""

import argparse
import re
import signal
from collections.abc import Mapping, Sequence
from threading import Event, current_thread, main_thread
from uuid import UUID

from .chains import CHAINS
from .config import ConfigurationError, load_settings
from .environment import EnvironmentFileError, load_environment
from .logging import create_logger
from .logging.types import Transport
from .providers.published import PublishedProvider
from .repository.connection import DatabaseConnectionError, make_connection_factory
from .runs.manual import run_manual
from .runs.schedule import run_scheduled
from .runs.worker import ConnectionFactory, ProviderFactory


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
    refresh = commands.add_parser("refresh", help="Admit and execute a full manual refresh")
    refresh.add_argument("--run-id", type=UUID, help="Optional existing API-admitted run")
    scheduled = commands.add_parser("scheduled", help="Claim and execute the Israel daily refresh")
    scheduled.add_argument("--timezone", choices=["Asia/Jerusalem"], default="Asia/Jerusalem")
    probe = commands.add_parser("probe", help="Run a bounded provider feasibility probe")
    probe.add_argument("--chains", type=_chains)
    probe.add_argument("--max-branches", type=_branches, default=1)
    pilot = commands.add_parser(
        "pilot", help="Validate production collection without database writes"
    )
    pilot.add_argument("--chains", type=_chains)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    provider_factory: ProviderFactory | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        process = load_environment(env)
        settings = load_settings(
            process,
            require_database=args.command in ("refresh", "scheduled")
            or getattr(args, "require_database", False),
        )
        chains = getattr(args, "chains", None) or settings.enabled_chains
        if any(chain not in settings.enabled_chains for chain in chains):
            raise ConfigurationError("Requested chains must be enabled in ENABLED_CHAINS")
    except (ConfigurationError, EnvironmentFileError) as error:
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
        **({"run_id": str(args.run_id)} if args.command == "refresh" and args.run_id else {}),
    )
    try:
        if args.command == "check-config":
            logger.info(
                "configuration.validated", "Process configuration is valid", chain_count=len(chains)
            )
            return 0
        if args.command == "probe":
            from .providers.trial import run_probe

            return run_probe(chains, settings, logger, max_branches=args.max_branches)
        if args.command == "pilot":
            from .pilot import run_pilot

            return run_pilot(chains, settings, logger, provider_factory or PublishedProvider)
        if args.command in ("refresh", "scheduled"):
            execution_id = process.get("GITHUB_RUN_ID", "")
            attempt = process.get("GITHUB_RUN_ATTEMPT", "1")
            if not re.fullmatch(r"[0-9]{1,30}", execution_id) or not re.fullmatch(
                r"[0-9]{1,10}", attempt
            ):
                logger.error("configuration.invalid", "GitHub execution correlation is required")
                return 2
            try:
                connect = (
                    connection_factory
                    if connection_factory is not None
                    else make_connection_factory(settings.database_url or "", env=process)
                )
            except DatabaseConnectionError as error:
                logger.error(
                    "configuration.invalid",
                    "Database connection configuration is invalid",
                    error_code=str(error),
                )
                return 2
            cancelled = Event()
            previous = None
            if current_thread() is main_thread():
                previous = signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
            try:
                parameters = dict(
                    execution_id=f"{execution_id}:{attempt}",
                    settings=settings,
                    connection_factory=connect,
                    provider_factory=PublishedProvider
                    if provider_factory is None
                    else provider_factory,
                    logger=logger,
                    cancelled=cancelled,
                )
                return (
                    run_manual(args.run_id, **parameters)
                    if args.command == "refresh"
                    else run_scheduled(**parameters)
                )
            finally:
                if previous is not None:
                    signal.signal(signal.SIGTERM, previous)
        logger.error(
            "command.unavailable",
            "Collection command is not enabled yet",
            error_code="UNSUPPORTED_COMMAND",
        )
        return 3
    finally:
        logger.flush()


if __name__ == "__main__":
    raise SystemExit(main())
