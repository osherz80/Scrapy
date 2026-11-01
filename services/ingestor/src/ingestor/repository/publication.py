"""Replace one current catalog and record its outcome under transactional fencing."""

import json
import re
from datetime import datetime, timedelta
from time import monotonic

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from ..collection import ChainCollection
from ..logging.types import Logger
from ..runs.ownership import OwnershipError, RunOwnership
from ..xml_items import XML_COLUMNS, XmlProduct
from .admission import _timeouts

_INSERT_COLUMNS = (
    "chain_id",
    *XML_COLUMNS,
    "sample_count",
    "subchain_id",
    "store_id",
    "xml_fields",
    "updated_at",
    "run_id",
)
_INSERT = (
    "INSERT INTO public.products ("
    + ",".join(_INSERT_COLUMNS)
    + ") VALUES ("
    + ",".join(["%s"] * len(_INSERT_COLUMNS))
    + ")"
)


class PublicationError(Exception):
    """Static publication diagnostic without product data or SQL details."""


def _aware(value: datetime | None) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _prepare(collection: ChainCollection):
    result = collection.aggregation
    attempted, successful = collection.attempted_branches, collection.successful_branches
    counters = (
        result.conflict_count,
        result.invalid_price_count,
        result.invalid_row_count,
        result.duplicate_row_count,
        result.missing_package_count,
        collection.failed_attempt_count,
    )
    if (
        not isinstance(result.products, tuple)
        or not 0 <= len(successful) <= 3
        or not len(successful) <= len(attempted) <= 9
        or len(set(attempted)) != len(attempted)
        or len(set(successful)) != len(successful)
        or not set(successful).issubset(attempted)
        or any(branch.chain_id != result.chain_id for branch in attempted)
        or type(result.successful_branch_count) is not int
        or result.successful_branch_count != len(successful)
        or collection.failed_attempt_count != len(attempted) - len(successful)
        or any(type(value) is not int or value < 0 for value in counters)
        or (result.products and not successful)
        or len({product.item_code for product in result.products}) != len(result.products)
    ):
        raise PublicationError("INVALID_PUBLICATION")
    sampled = [
        {
            "subchain_id": branch.subchain_id,
            "store_id": branch.store_id,
            "successful": branch in successful,
        }
        for branch in attempted
    ]
    if len(json.dumps(sampled, ensure_ascii=False).encode("utf-8")) > 4096:
        raise PublicationError("INVALID_PUBLICATION")
    if result.products and not _aware(result.source_updated_at):
        raise PublicationError("INVALID_PUBLICATION")
    rows = []
    for product in result.products:
        if (
            not isinstance(product, XmlProduct)
            or product.chain_id != result.chain_id
            or type(product.sample_count) is not int
            or not 1 <= product.sample_count <= len(successful)
            or product.selected_branch not in successful
            or not isinstance(product.fields, dict)
            or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in product.fields.items()
            )
            or product.fields.get("item_code") != product.item_code
            or not product.item_code
        ):
            raise PublicationError("INVALID_PUBLICATION")
        rows.append(
            (
                product.chain_id,
                *(product.fields.get(c) for c in XML_COLUMNS),
                product.sample_count,
                product.selected_branch.subchain_id,
                product.selected_branch.store_id,
                Jsonb(product.fields),
            )
        )
    return rows, Jsonb(sampled)


def _check_lease(connection, owner, chain_id, started_at):
    lease = connection.execute(
        "SELECT run_id,owner_token,expires_at FROM public.chain_leases "
        "WHERE chain_id=%s FOR UPDATE",
        (chain_id,),
    ).fetchone()
    now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    if min(owner.deadline, started_at + timedelta(minutes=45)) <= now:
        raise OwnershipError("RUN_DEADLINE_EXCEEDED")
    if lease is None or lease[0] != owner.run_id or lease[1] != owner.token or lease[2] <= now:
        raise OwnershipError("LEASE_LOST")
    return now


def _lock_chain(connection, owner, chain_id):
    run = connection.execute(
        "SELECT status,requested_chains,started_at FROM public.refresh_runs WHERE id=%s FOR UPDATE",
        (owner.run_id,),
    ).fetchone()
    if run is None or run[0] != "RUNNING" or tuple(sorted(run[1])) != owner.chains:
        raise OwnershipError("LEASE_LOST")
    state = connection.execute(
        "SELECT status FROM public.refresh_run_chains WHERE run_id=%s AND chain_id=%s FOR UPDATE",
        (owner.run_id, chain_id),
    ).fetchone()
    if state is None or chain_id not in owner.chains:
        raise PublicationError("UNAUTHORIZED_CHAIN")
    if state[0] not in ("PENDING", "RUNNING"):
        raise PublicationError("CHAIN_ALREADY_FINISHED")
    return run[2], _check_lease(connection, owner, chain_id, run[2])


def start_chain(connection: psycopg.Connection, owner: RunOwnership, chain_id: str) -> None:
    """Record actual collection start only while ownership is valid."""
    if not connection.autocommit or connection.info.transaction_status != TransactionStatus.IDLE:
        raise PublicationError("AUTOCOMMIT_CONNECTION_REQUIRED")
    with connection.transaction():
        _timeouts(connection)
        _, now = _lock_chain(connection, owner, chain_id)
        connection.execute(
            "UPDATE public.refresh_run_chains SET status='RUNNING',"
            "started_at=coalesce(started_at,%s) WHERE run_id=%s AND chain_id=%s",
            (now, owner.run_id, chain_id),
        )


def publish_collection(
    connection: psycopg.Connection,
    owner: RunOwnership,
    collection: ChainCollection,
    *,
    logger: Logger | None = None,
    failure_code: str | None = None,
) -> bool:
    """Stage one chain in memory, then atomically replace or preserve its catalog.

    Returns false for a valid but unpublishable result and marks that chain failed.
    All exceptions roll back products, metadata, outcome and lease changes. The
    run remains RUNNING until the separate run-finalization/recovery layer acts.
    """
    result = collection.aggregation
    started = monotonic()
    if logger:
        logger = logger.child(run_id=str(owner.run_id), chain_id=result.chain_id)
    try:
        if (
            not connection.autocommit
            or connection.info.transaction_status != TransactionStatus.IDLE
        ):
            raise PublicationError("AUTOCOMMIT_CONNECTION_REQUIRED")
        if result.chain_id not in owner.chains:
            raise PublicationError("UNAUTHORIZED_CHAIN")
        if failure_code is not None and (
            result.can_publish
            or not isinstance(failure_code, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", failure_code)
        ):
            raise PublicationError("INVALID_FAILURE_CODE")
        rows, sampled = _prepare(collection)
        with connection.transaction():
            _timeouts(connection)
            run_started_at, now = _lock_chain(connection, owner, result.chain_id)
            if result.can_publish:
                connection.execute(
                    "DELETE FROM public.products WHERE chain_id=%s", (result.chain_id,)
                )
                with connection.cursor() as cursor:
                    cursor.executemany(_INSERT, ((*row, now, owner.run_id) for row in rows))
            finished_at = connection.execute("SELECT clock_timestamp()").fetchone()[0]
            if result.can_publish:
                connection.execute(
                    "UPDATE public.chains SET current_run_id=%s,catalog_updated_at=%s,"
                    "source_updated_at=%s,product_count=%s WHERE id=%s",
                    (
                        owner.run_id,
                        finished_at,
                        result.source_updated_at,
                        len(rows),
                        result.chain_id,
                    ),
                )
            error_code = (
                None
                if result.can_publish
                else (
                    failure_code
                    or (
                        "NO_SUCCESSFUL_BRANCHES"
                        if not result.successful_branch_count
                        else "NO_PUBLISHABLE_PRODUCTS"
                    )
                )
            )
            connection.execute(
                "UPDATE public.refresh_run_chains SET status=%s,attempt_count=%s,"
                "successful_branch_count=%s,sampled_branch_ids=%s,product_count=%s,invalid_row_count=%s,"
                "conflict_count=%s,source_updated_at=%s,error_code=%s,error_message=NULL,"
                "started_at=coalesce(started_at,%s),finished_at=%s WHERE run_id=%s AND chain_id=%s",
                (
                    "SUCCEEDED" if result.can_publish else "FAILED",
                    len(collection.attempted_branches),
                    result.successful_branch_count,
                    sampled,
                    len(rows),
                    result.invalid_row_count,
                    result.conflict_count,
                    result.source_updated_at,
                    error_code,
                    now,
                    finished_at,
                    owner.run_id,
                    result.chain_id,
                ),
            )
            # Long insert batches or triggers may outlive the lease while holding
            # its lock. Recheck using current DB time before releasing ownership.
            _check_lease(connection, owner, result.chain_id, run_started_at)
            connection.execute(
                "DELETE FROM public.chain_leases WHERE chain_id=%s AND run_id=%s",
                (result.chain_id, owner.run_id),
            )
    except Exception as error:
        if logger:
            logger.error(
                "publication.failed",
                "Catalog publication rolled back",
                error=error,
                duration_ms=round((monotonic() - started) * 1000),
            )
        raise
    if logger:
        logger.info(
            "publication.finished",
            "Chain outcome committed",
            published=result.can_publish,
            product_count=len(rows),
            source_updated_at=(
                result.source_updated_at.isoformat() if result.source_updated_at else None
            ),
            source_age_hours=(
                round((finished_at - result.source_updated_at).total_seconds() / 3600, 2)
                if result.source_updated_at
                else None
            ),
            duration_ms=round((monotonic() - started) * 1000),
        )
    return result.can_publish
