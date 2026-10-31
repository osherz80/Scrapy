"""Internal XML reader. Callers must exhaust it before accepting any catalog."""

import io
from collections.abc import Iterator
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .providers.stream import SourceError


def iter_price_items(
    xml: bytes,
    headers: dict[str, str],
    *,
    max_bytes: int = 100_000_000,
) -> Iterator[dict[str, str]]:
    if len(xml) > max_bytes:
        raise SourceError("SIZE_LIMIT")
    stack: list[str] = []
    container = None
    try:
        events = ElementTree.iterparse(
            io.BytesIO(xml),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for event, element in events:
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if event == "start":
                stack.append(tag)
                if tag == "items":
                    if container is not None:
                        raise SourceError("INVALID_CATALOG")
                    container = element
                continue
            if len(stack) == 2 and tag in ("chainid", "subchainid", "storeid"):
                value = (element.text or "").strip()
                if tag in headers and headers[tag] != value:
                    raise SourceError("AMBIGUOUS_HEADER")
                headers[tag] = value
            if tag == "item" and len(stack) >= 2 and stack[-2] == "items":
                fields: dict[str, str] = {}
                duplicate = False
                for child in element:
                    key = child.tag.rsplit("}", 1)[-1].lower()
                    duplicate = duplicate or key in fields
                    fields[key] = (child.text or "").strip()
                if duplicate:
                    fields["__ambiguous_row__"] = "1"
                element.clear()
                container.remove(element)
                yield fields
            stack.pop()
    except (ParseError, DefusedXmlException, ValueError, LookupError):
        raise SourceError("INVALID_CATALOG") from None
