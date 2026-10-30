from datetime import UTC, datetime, timedelta

import pytest

from ingestor.providers.selected import select_catalogs
from ingestor.providers.stream import SourceError
from ingestor.providers.types import (
    Branch,
    BranchIdentity,
    BranchKind,
    CatalogCandidate,
    FileKind,
    PublishedFile,
)

NOW = datetime(2026, 10, 30, 6, tzinfo=UTC)


def branch(store="001", subchain="001", kind=BranchKind.PHYSICAL_GROCERY):
    return Branch(BranchIdentity("rami-levy", subchain, store), kind)


def file(branch, *, published=NOW, kind=FileKind.PRICE_FULL, suffix="060000"):
    return PublishedFile(
        branch.identity,
        kind,
        f"{kind.value}7290058140886-001-001-20261030-{suffix}.gz",
        "https://source.test/file?signature=synthetic-secret",
        published,
    )


def test_latest_full_files_are_selected_after_consuming_all_pages():
    a = branch()
    old, new = file(a, published=NOW - timedelta(days=1)), file(a, suffix="070000")
    pages = iter([old, file(a, kind=FileKind.PRICE, published=NOW + timedelta(hours=1)), new])
    result = select_catalogs((a,), pages, chain_id="rami-levy")
    assert len(result) == 1
    assert result[0].file is new


def test_same_store_number_in_different_subchains_stays_distinct():
    a, b = branch(subchain="001"), branch(subchain="002")
    result = select_catalogs((a, b), (file(a), file(b)), chain_id="rami-levy")
    assert {candidate.branch.identity for candidate in result} == {a.identity, b.identity}


@pytest.mark.parametrize(
    "kind", [BranchKind.ONLINE_ONLY, BranchKind.PHARMACY_ONLY, BranchKind.UNKNOWN]
)
def test_ineligible_or_unverified_branches_are_not_guessed_as_physical(kind):
    a = branch(kind=kind)
    assert select_catalogs((a,), (file(a),), chain_id="rami-levy") == ()


def test_missing_timestamp_is_an_attemptable_failure_not_an_older_file_fallback():
    a = branch()
    result = select_catalogs((a,), (file(a), file(a, published=None)), chain_id="rami-levy")
    assert result[0].file is None
    assert result[0].metadata_error_code == "MISSING_SOURCE_TIME"


def test_partial_pagination_cannot_return_an_incomplete_sampling_roster():
    a = branch()

    def incomplete():
        yield file(a)
        raise SourceError("TIME_LIMIT")

    with pytest.raises(SourceError, match="TIME_LIMIT"):
        select_catalogs((a,), incomplete(), chain_id="rami-levy")


def test_conflicting_branch_classification_fails_closed():
    a, conflicting = branch(), branch(kind=BranchKind.ONLINE_ONLY)
    with pytest.raises(SourceError, match="AMBIGUOUS_BRANCH"):
        select_catalogs((a, conflicting), (file(a),), chain_id="rami-levy")


def test_signed_source_url_is_not_in_reference_representation():
    assert "synthetic-secret" not in repr(file(branch()))


def test_naive_listing_timestamp_cannot_cross_provider_boundary():
    with pytest.raises(ValueError, match="timezone-aware"):
        file(branch(), published=datetime(2026, 10, 30, 6))


def test_candidate_requires_exactly_one_reference_or_metadata_failure():
    a = branch()
    with pytest.raises(ValueError):
        CatalogCandidate(a, None)
    with pytest.raises(ValueError):
        CatalogCandidate(a, file(a), "MISSING_SOURCE_TIME")
