"""Provider-independent branch and file contracts; source URLs are never CLI input."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class BranchKind(StrEnum):
    PHYSICAL_GROCERY = "physical_grocery"
    ONLINE_ONLY = "online_only"
    PHARMACY_ONLY = "pharmacy_only"
    UNKNOWN = "unknown"


class FileKind(StrEnum):
    PRICE_FULL = "PriceFull"
    PRICE = "Price"
    PROMO_FULL = "PromoFull"
    PROMO = "Promo"
    STORES = "Stores"


@dataclass(frozen=True, order=True)
class BranchIdentity:
    chain_id: str
    subchain_id: str
    store_id: str

    def __post_init__(self) -> None:
        if any(
            not part or part != part.strip()
            for part in (
                self.chain_id,
                self.subchain_id,
                self.store_id,
            )
        ):
            raise ValueError("Branch identity requires chain, subchain and store")


@dataclass(frozen=True)
class Branch:
    identity: BranchIdentity
    kind: BranchKind


@dataclass(frozen=True)
class PublishedFile:
    identity: BranchIdentity
    kind: FileKind
    name: str
    source_url: str = field(repr=False)
    published_at: datetime | None

    def __post_init__(self) -> None:
        if self.published_at is not None and self.published_at.utcoffset() is None:
            raise ValueError("Source timestamp must be timezone-aware")


@dataclass(frozen=True)
class CatalogCandidate:
    branch: Branch
    file: PublishedFile | None
    metadata_error_code: str | None = None


class Provider(Protocol):
    def list_branches(self) -> tuple[Branch, ...]: ...
    def iter_files(self) -> Iterator[PublishedFile]: ...
    def download(self, file: PublishedFile) -> bytes: ...
    def close(self) -> None: ...
