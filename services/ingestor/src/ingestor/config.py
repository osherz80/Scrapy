"""Validate explicitly supplied process settings without opening configuration files."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .chains import CHAINS, DEFERRED_CHAIN_IDS


class ConfigurationError(ValueError):
    """A setting is missing or invalid; messages contain names, never values."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str | None = field(repr=False)
    enabled_chains: tuple[str, ...]
    provider_timeout_seconds: int
    provider_max_decompressed_bytes: int
    refresh_stale_hours: int
    run_lease_seconds: int
    run_timeout_minutes: int
    heartbeat_seconds: int
    log_provider: str
    log_level: str
    log_env: str
    app_version: str


def _positive(
    env: Mapping[str, str], name: str, default: int, *, maximum: int | None = None
) -> int:
    try:
        value = int(env.get(name, str(default)))
        if value <= 0 or (maximum is not None and value > maximum):
            raise ValueError
        return value
    except ValueError:
        limit = f" no greater than {maximum}" if maximum is not None else ""
        raise ConfigurationError(f"{name} must be a positive integer{limit}") from None


def load_settings(
    env: Mapping[str, str] | None = None, *, require_database: bool = False
) -> Settings:
    env = os.environ if env is None else env
    database_url = env.get("DATABASE_URL")
    if require_database and not database_url:
        raise ConfigurationError("DATABASE_URL is required")
    if database_url:
        try:
            parsed = urlsplit(
                database_url.replace("[YOUR-PASSWORD]", "")
                if env.get("DATABASE_PASSWORD")
                else database_url
            )
            valid = parsed.scheme in ("postgres", "postgresql") and parsed.hostname and parsed.path
            if not valid or not parsed.path.strip("/") or parsed.fragment:
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise ConfigurationError("DATABASE_URL must be a PostgreSQL connection URL") from None
    known_chains = tuple(chain.id for chain in CHAINS)
    default_chains = tuple(chain for chain in known_chains if chain not in DEFERRED_CHAIN_IDS)
    enabled = tuple(
        part.strip() for part in env.get("ENABLED_CHAINS", ",".join(default_chains)).split(",")
    )
    if (
        not enabled
        or len(set(enabled)) != len(enabled)
        or any(c not in known_chains for c in enabled)
    ):
        raise ConfigurationError("ENABLED_CHAINS must contain distinct configured chain IDs")
    level = env.get("LOG_LEVEL", "info")
    if level not in ("debug", "info", "warn", "error", "fatal"):
        raise ConfigurationError("LOG_LEVEL is unsupported")
    provider = env.get("LOG_PROVIDER", "console")
    if provider != "console":
        raise ConfigurationError("LOG_PROVIDER is unsupported; use console")
    lease = _positive(env, "RUN_LEASE_SECONDS", 300, maximum=300)
    heartbeat = _positive(env, "HEARTBEAT_SECONDS", 30)
    if heartbeat >= lease:
        raise ConfigurationError("HEARTBEAT_SECONDS must be less than RUN_LEASE_SECONDS")
    return Settings(
        database_url=database_url,
        enabled_chains=enabled,
        provider_timeout_seconds=_positive(env, "PROVIDER_TIMEOUT_SECONDS", 60),
        provider_max_decompressed_bytes=_positive(
            env, "PROVIDER_MAX_DECOMPRESSED_BYTES", 100_000_000
        ),
        refresh_stale_hours=_positive(env, "REFRESH_STALE_HOURS", 48),
        run_lease_seconds=lease,
        run_timeout_minutes=_positive(env, "RUN_TIMEOUT_MINUTES", 45, maximum=45),
        heartbeat_seconds=heartbeat,
        log_provider=provider,
        log_level=level,
        log_env=env.get("LOG_ENV", "development"),
        app_version=env.get("APP_VERSION") or env.get("GITHUB_SHA") or "unknown",
    )
