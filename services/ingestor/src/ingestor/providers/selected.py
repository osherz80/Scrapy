"""Build a complete sampling inventory without guessing branch eligibility."""

import re
from collections.abc import Iterable, Sequence

from ..chains import DEFERRED_CHAIN_IDS
from .stream import SourceError
from .types import Branch, BranchIdentity, BranchKind, CatalogCandidate, FileKind, PublishedFile

_FULL_FILE = re.compile(r"^PriceFull\d{13}-.+\.(?:gz|xml|zip)$", re.IGNORECASE)


def select_catalogs(
    branches: Sequence[Branch],
    files: Iterable[PublishedFile],
    *,
    chain_id: str,
) -> tuple[CatalogCandidate, ...]:
    if chain_id in DEFERRED_CHAIN_IDS:
        raise SourceError("SOURCE_DEFERRED")
    roster: dict[BranchIdentity, Branch] = {}
    for branch in branches:
        if branch.identity.chain_id != chain_id:
            continue
        if branch.identity in roster and roster[branch.identity] != branch:
            raise SourceError("AMBIGUOUS_BRANCH")
        roster[branch.identity] = branch
    eligible = {key for key, branch in roster.items() if branch.kind == BranchKind.PHYSICAL_GROCERY}
    latest: dict[BranchIdentity, PublishedFile] = {}
    unknown_times: set[BranchIdentity] = set()
    # Consume the entire listing. If pagination fails, propagate it before
    # returning any roster: partial listings would bias uniform branch sampling.
    for ref in files:
        if ref.identity not in eligible or ref.kind != FileKind.PRICE_FULL:
            continue
        if not _FULL_FILE.fullmatch(ref.name):
            continue
        if ref.published_at is None:
            unknown_times.add(ref.identity)
            continue
        previous = latest.get(ref.identity)
        if previous is None or (ref.published_at, ref.name) > (
            previous.published_at,
            previous.name,
        ):
            latest[ref.identity] = ref
    candidates = []
    for identity in sorted(set(latest) | unknown_times):
        if identity in unknown_times:
            candidates.append(CatalogCandidate(roster[identity], None, "MISSING_SOURCE_TIME"))
        else:
            candidates.append(CatalogCandidate(roster[identity], latest[identity]))
    return tuple(candidates)
