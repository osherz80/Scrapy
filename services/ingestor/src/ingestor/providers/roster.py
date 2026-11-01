"""Strict publisher roster and filename metadata; no product data or raw files."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from ..timestamps import source_timestamp
from .stream import SourceError
from .types import Branch, BranchIdentity, BranchKind, FileKind, identifier_key


def _tag(element):
    return element.tag.rsplit("}", 1)[-1].lower()


def _fields(element):
    result = {}
    for child in element:
        if len(child):
            continue
        key = _tag(child)
        if key in result:
            raise SourceError("INVALID_ROSTER")
        result[key] = (child.text or "").strip()
    return result


def parse_roster(
    xml: bytes,
    *,
    chain_id: str,
    source_chain_id: str,
    subchain_aliases: Mapping[str, str] | None = None,
    max_bytes: int = 100_000_000,
) -> tuple[Branch, ...]:
    if len(xml) > max_bytes:
        raise SourceError("SIZE_LIMIT")
    try:
        root = ElementTree.fromstring(
            xml, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (ParseError, DefusedXmlException, ValueError, LookupError):
        raise SourceError("INVALID_ROSTER") from None
    if _fields(root).get("chainid") != source_chain_id:
        raise SourceError("IDENTITY_MISMATCH")
    aliases = subchain_aliases or {}
    branches, seen = [], set()
    pending = [(root, None, None)]
    while pending:
        element, subchain, parent = pending.pop()
        tag = _tag(element)
        if tag == "subchain":
            if subchain is not None:
                raise SourceError("INVALID_ROSTER")
            subchain = _fields(element).get("subchainid")
        if tag == "store":
            fields = _fields(element)
            if parent != "stores" or any(len(child) for child in element):
                raise SourceError("INVALID_ROSTER")
            direct_sub = fields.get("subchainid")
            if subchain and direct_sub and identifier_key(subchain) != identifier_key(direct_sub):
                raise SourceError("INVALID_ROSTER")
            sub = subchain or direct_sub or ""
            store = fields.get("storeid", "")
            if any(not re.fullmatch(r"[0-9]{1,32}", value) for value in (sub, store)):
                raise SourceError("INVALID_ROSTER")
            sub = aliases.get(identifier_key(sub), sub)
            key = (identifier_key(sub), identifier_key(store))
            if key in seen:
                raise SourceError("INVALID_ROSTER")
            seen.add(key)
            kind = {
                "1": BranchKind.PHYSICAL_GROCERY,
                "3": BranchKind.PHYSICAL_GROCERY,
                "2": BranchKind.ONLINE_ONLY,
            }.get(fields.get("storetype"), BranchKind.UNKNOWN)
            branches.append(Branch(BranchIdentity(chain_id, sub, store), kind))
            continue
        pending.extend((child, subchain, tag) for child in reversed(element))
    if not branches:
        raise SourceError("INVALID_ROSTER")
    return tuple(branches)


@dataclass(frozen=True, slots=True)
class Filename:
    kind: FileKind
    source_chain_id: str
    subchain_id: str | None
    store_id: str | None
    published_at: datetime | None


def parse_filename(name: str) -> Filename | None:
    match = re.fullmatch(
        r"(PriceFull|StoresFull|Stores)([0-9]{13})-([0-9-]+)\.(?:gz|xml|zip)", name, re.I
    )
    if match is None:
        return None
    kind = FileKind.PRICE_FULL if match[1].lower() == "pricefull" else FileKind.STORES
    parts = match[3].split("-")
    stamp, identity = None, []
    if len(parts) >= 2 and len(parts[-1]) == 6 and len(parts[-2]) in (8, 14):
        stamp = parts[-2] + parts[-1] if len(parts[-2]) == 8 else parts[-2]
        if len(parts[-2]) == 14 and parts[-2][-6:] != parts[-1]:
            return None
        identity = parts[:-2]
    elif len(parts[-1]) in (12, 14):
        stamp, identity = parts[-1], parts[:-1]
    elif (
        kind == FileKind.STORES
        and len(parts) >= 2
        and len(parts[-2]) == 8
        and 1 <= len(parts[-1]) <= 5
        and parts[-2].isascii()
        and parts[-2].isdecimal()
        and parts[-1].isascii()
        and parts[-1].isdecimal()
    ):
        # Shufersal's Stores name carries a date with an abbreviated trailing
        # token instead of an HHMMSS time (...-20261101-020.gz). Only the date
        # is reliable here; the XML exposes LastUpdateDate/LastUpdateTime when
        # exact source timing is needed.
        stamp, identity = parts[-2], parts[:-2]
    if not stamp or not 1 <= len(identity) <= 2 or any(not value for value in identity):
        return None
    try:
        if len(stamp) == 14:
            value = datetime.strptime(stamp, "%Y%m%d%H%M%S")
        elif len(stamp) == 12:
            value = datetime.strptime(stamp, "%Y%m%d%H%M")
        else:
            value = datetime.strptime(stamp, "%Y%m%d")
        published = source_timestamp(value)
    except (ValueError, SourceError):
        published = None
    return Filename(
        kind,
        match[2],
        identity[0] if len(identity) == 2 else None,
        identity[-1] if kind == FileKind.PRICE_FULL else None,
        published,
    )
