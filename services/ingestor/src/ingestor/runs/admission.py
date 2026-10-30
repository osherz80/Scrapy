"""Validated admission inputs and safe coordination diagnostics."""

from dataclasses import dataclass
from uuid import UUID

from ..chains import CHAINS, DEFERRED_CHAIN_IDS


class AdmissionError(Exception):
    """Static public code; never includes database or caller-supplied text."""


@dataclass(frozen=True, slots=True)
class AdmittedRun:
    id: UUID
    chains: tuple[str, ...]


def validate_request(chains: tuple[str, ...], origin: str) -> tuple[str, ...]:
    if origin not in ("MANUAL", "SCHEDULED"):
        raise AdmissionError("INVALID_RUN_ORIGIN")
    known = {chain.id for chain in CHAINS}
    if (
        not isinstance(chains, tuple)
        or not 1 <= len(chains) <= 10
        or any(not isinstance(chain, str) or chain not in known for chain in chains)
        or len(set(chains)) != len(chains)
    ):
        raise AdmissionError("INVALID_REQUESTED_CHAINS")
    if DEFERRED_CHAIN_IDS.intersection(chains):
        raise AdmissionError("SOURCE_DEFERRED")
    return tuple(sorted(chains))
