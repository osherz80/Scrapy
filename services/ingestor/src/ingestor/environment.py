"""Load only the scraper-root .env, without displaying or mutating secrets."""

import io
import os
from collections.abc import Mapping
from pathlib import Path

from dotenv.parser import parse_stream

_MAX_BYTES = 1_048_576


class EnvironmentFileError(ValueError):
    """Static diagnostic code; never contains file contents or parser details."""


def _project_root() -> Path | None:
    # Fixed checkout anchor or explicit launch directory, never a parent search.
    checkout = Path(__file__).resolve().parents[4]
    if (checkout / "SPEC-supermarket-scraper.md").is_file():
        return checkout
    launch = Path.cwd().resolve()
    return launch if (launch / "SPEC-supermarket-scraper.md").is_file() else None


def load_environment(
    env: Mapping[str, str] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, str]:
    """Explicit mappings bypass files; process variables override local defaults."""
    if env is not None:
        return dict(env)
    project = _project_root() if root is None else root.resolve()
    if project is None:
        return dict(os.environ)
    path = project / ".env"
    if path.is_symlink() or not path.resolve().is_relative_to(project):
        raise EnvironmentFileError("ENV_FILE_OUTSIDE_PROJECT")
    try:
        with path.open("rb") as source:
            payload = source.read(_MAX_BYTES + 1)
    except FileNotFoundError:
        return dict(os.environ)
    except OSError:
        raise EnvironmentFileError("ENV_FILE_UNREADABLE") from None
    if len(payload) > _MAX_BYTES:
        raise EnvironmentFileError("ENV_FILE_TOO_LARGE")
    try:
        contents = payload.decode("utf-8-sig")
    except UnicodeError:
        raise EnvironmentFileError("ENV_FILE_INVALID") from None
    values = {}
    # Pinned low-level parser exposes errors without logging source lines.
    # It also avoids os.environ mutation and credential-altering interpolation.
    for binding in parse_stream(io.StringIO(contents)):
        if binding.error:
            raise EnvironmentFileError("ENV_FILE_INVALID")
        if binding.key is not None and binding.value is not None:
            values[binding.key] = binding.value
    return {**values, **os.environ}
