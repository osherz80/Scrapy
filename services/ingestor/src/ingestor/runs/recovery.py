"""Terminal run policy and bounded operational status records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class RecoveryError(Exception):
    """Static recovery diagnostic without credentials or source data."""


def final_status(chain_statuses: tuple[str, ...]) -> str:
    if not chain_statuses or any(
        status not in ("SUCCEEDED", "FAILED") for status in chain_statuses
    ):
        raise RecoveryError("UNFINISHED_CHAINS")
    if all(status == "SUCCEEDED" for status in chain_statuses):
        return "SUCCEEDED"
    if all(status == "FAILED" for status in chain_statuses):
        return "FAILED"
    return "PARTIAL_FAILED"


@dataclass(frozen=True, slots=True)
class ChainStatus:
    chain_id: str
    status: str
    attempt_count: int
    successful_branch_count: int
    product_count: int
    invalid_row_count: int
    conflict_count: int
    source_updated_at: datetime | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class RunStatus:
    id: UUID
    status: str
    dispatch_state: str
    requested_chains: tuple[str, ...]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    github_run_id: str | None
    chains: tuple[ChainStatus, ...]
