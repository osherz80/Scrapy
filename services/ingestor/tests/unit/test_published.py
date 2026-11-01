import gzip
from dataclasses import replace
from time import monotonic

import httpx
import pytest

from ingestor.config import load_settings
from ingestor.providers.http import BoundedClient
from ingestor.providers.published import PublishedProvider
from ingestor.providers.stream import SourceError


def roster(chain="7290058140886", sub="001"):
    return (
        f"<Root><ChainId>{chain}</ChainId><SubChains><SubChain><SubChainId>{sub}</SubChainId>"
        "<Stores><Store><StoreId>007</StoreId><StoreType>1</StoreType></Store>"
        "<Store><StoreId>008</StoreId><StoreType>2</StoreType></Store></Stores>"
        "</SubChain></SubChains></Root>"
    ).encode()


def provider(chain, handler, **kwargs):
    client = BoundedClient(
        allowed_hosts=frozenset(
            {
                "url.publishedprices.co.il",
                "laibcatalog.co.il",
                "shop.hazi-hinam.co.il",
                "prices.shufersal.co.il",
            }
        ),
        allow_azure=True,
        timeout_seconds=60,
        max_bytes=1000000,
        transport=httpx.MockTransport(handler),
    )
    return PublishedProvider(chain, load_settings({}), monotonic() + 60, client=client, **kwargs)


def cerberus_handler(*, bad=None):
    def handler(request):
        if request.url.path == "/login":
            return httpx.Response(200, text='<meta name="csrftoken" content="first">')
        if request.url.path == "/login/user":
            return httpx.Response(302, headers={"location": "/file"})
        if request.url.path == "/file":
            return httpx.Response(200, text='<meta name="csrftoken" content="second">')
        if request.url.path == "/file/json/dir":
            form = dict(httpx.QueryParams(request.content.decode()))
            if form["sSearch"] == "Stores":
                names = ["Stores7290058140886-000-20261031-060000.xml"]
            else:
                names = [
                    "PriceFull7290058140886-001-007-20261031-060000.gz",
                    "PriceFull7290058140886-001-008-20261031-060000.gz",
                ]
            start = int(form.get("iDisplayStart", "0"))
            if bad == "repeat":
                start = 0
            subset = names[start : start + 1]
            if bad == "empty" and start:
                subset = []
            total = len(names) + (1 if bad == "total" and start else 0)
            if bad == "fraction":
                total += 0.5
            return httpx.Response(
                200,
                json={
                    "iTotalRecords": len(names),
                    "iTotalDisplayRecords": total,
                    "aaData": [{"fname": name, "type": "file"} for name in subset],
                },
            )
        if request.url.path.endswith(".xml"):
            return httpx.Response(200, content=roster())
        return httpx.Response(200, content=b"catalog")

    return handler


def shufersal_roster():
    return (
        b"<Chain><ChainID>7290027600007</ChainID>"
        b"<LastUpdateDate>2026-11-01</LastUpdateDate>"
        b"<LastUpdateTime>02:01:10</LastUpdateTime>"
        b"<SubChains><SubChain><SubChainID>1</SubChainID><Stores>"
        b"<Store><StoreId>001</StoreId><StoreType>1</StoreType></Store>"
        b"<Store><StoreId>002</StoreId><StoreType>1</StoreType></Store>"
        b"</Stores></SubChain></SubChains></Chain>"
    )


def shufersal_blob(name):
    return (
        "https://pricesprodpublic.blob.core.windows.net/pricefull/"
        f"{name}?sv=2014-02-14&amp;sr=b&amp;sig=test"
    )


def shufersal_page(*, cat, page, bad=None):
    if cat == 5:
        if bad == "no-stores":
            return "<html><body></body></html>"
        name = "Stores7290027600007-000-20261101-020.gz"
        return f'<html><body><a href="{shufersal_blob(name)}">file</a></body></html>'
    names = {
        1: "PriceFull7290027600007-001-001-20261101-032630.gz",
        2: "PriceFull7290027600007-001-002-20261101-032630.gz",
    }
    nav = [2] if page == 1 else [1]
    selected = {page: names[page]} if page in names else {}
    if bad == "empty" and page == 2:
        selected = {}
    if bad == "repeat" and page == 2:
        selected = {2: names[1]}
    if bad == "grow" and page == 2:
        nav = [1, 3]
    names = selected
    links = "".join(f'<a href="{shufersal_blob(name)}">file</a>' for name in names.values())
    links += (
        '<a href="/FileObject/UpdateCategory?catID=2&amp;storeId=0&amp;sort=Time&amp;'
        'sortdir=ASC">sort</a>'
    )
    links += "".join(
        f'<a href="/FileObject/UpdateCategory?catID=2&amp;storeId=0&amp;page={value}">{value}</a>'
        for value in nav
    )
    return f"<html><body>{links}</body></html>"


def shufersal_handler(*, bad=None):
    def handler(request):
        if request.url.host.endswith("blob.core.windows.net"):
            if request.url.path.endswith("Stores7290027600007-000-20261101-020.gz"):
                return httpx.Response(200, content=gzip.compress(shufersal_roster()))
            return httpx.Response(200, content=b"catalog")
        if request.url.path != "/FileObject/UpdateCategory":
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=shufersal_page(
                cat=int(request.url.params["catID"]),
                page=int(request.url.params["page"]),
                bad=bad,
            ),
        )

    return handler


def test_shufersal_follows_advertised_last_page_and_maps_roster_identities():
    pages = []
    base = shufersal_handler()

    def handler(request):
        if request.url.path == "/FileObject/UpdateCategory":
            pages.append(request.url.params["page"])
        return base(request)

    with provider("shufersal", handler) as source:
        branches = source.list_branches()
        files = tuple(source.iter_files())
        assert [(branch.identity.subchain_id, branch.identity.store_id) for branch in branches] == [
            ("1", "001"),
            ("1", "002"),
        ]
        assert [file.identity.store_id for file in files] == ["001", "002"]
        assert source.download(files[0]) == b"catalog"
    assert pages == ["1", "2", "1"]


@pytest.mark.parametrize("bad", ["empty", "repeat", "grow"])
def test_shufersal_rejects_incomplete_or_changing_listings(bad):
    with provider("shufersal", shufersal_handler(bad=bad)) as source:
        with pytest.raises(SourceError, match="INCOMPLETE_LISTING"):
            source.list_branches()


def test_shufersal_requires_a_nonempty_listing_for_every_category():
    with provider("shufersal", shufersal_handler(bad="no-stores")) as source:
        with pytest.raises(SourceError, match="INCOMPLETE_LISTING"):
            source.list_branches()


def test_cerberus_consumes_all_reported_pages_once_and_caches_complete_inventory():
    calls = []
    base = cerberus_handler()

    def handler(request):
        calls.append(request)
        return base(request)

    with provider("rami-levy", handler) as source:
        branches = source.list_branches()
        assert len(branches) == 2
        assert len(tuple(source.iter_files())) == 2
        assert len(calls) == 7  # login GET/POST/redirect, Stores, two PriceFull pages, roster
        file = next(source.iter_files())
        assert source.download(file) == b"catalog"
        with pytest.raises(SourceError, match="UNLISTED_FILE"):
            source.download(replace(file, source_url="https://unapproved.test/private"))


@pytest.mark.parametrize("bad", ["repeat", "empty", "total", "fraction"])
def test_cerberus_rejects_incomplete_or_changing_listings_before_sampling(bad):
    with provider("rami-levy", cerberus_handler(bad=bad)) as source:
        with pytest.raises(SourceError, match="INCOMPLETE_LISTING"):
            source.list_branches()


def test_failed_authentication_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text="not a login page")

    with provider("rami-levy", handler) as source:
        with pytest.raises(SourceError, match="AUTH_FAILED"):
            source.list_branches()
    assert len(calls) == 1


def test_laib_full_snapshot_and_fourteen_digit_stores_time():
    def handler(request):
        if request.url.path.endswith("getfiles"):
            return httpx.Response(
                200,
                json=[
                    {"fileName": name}
                    for name in (
                        "Stores7290696200003-000-20261031060100-060100.gz",
                        "PriceFull7290696200003-001-007-20261031-060000.gz",
                    )
                ],
            )
        return httpx.Response(200, content=roster("7290696200003"))

    with provider("victory", handler) as source:
        assert len(source.list_branches()) == 2
        assert len(tuple(source.iter_files())) == 1


def test_hatzi_follows_advertised_pages_and_preserves_blob_links():
    def handler(request):
        if request.url.host.endswith("blob.core.windows.net"):
            return httpx.Response(200, content=roster("7290700100008", "000"))
        kind, page = request.url.params["t"], request.url.params["p"]
        name = (
            "StoresFull7290700100008-000-20261031-060000.gz"
            if kind == "3"
            else f"PriceFull7290700100008-000-00{6 + int(page)}-20261031-060000.gz"
        )
        return httpx.Response(
            200,
            text=f'<a href="https://files.blob.core.windows.net/x/{name}">file</a>'
            '<a class="pagination-link" href="?p=1">1</a>'
            + ('<a class="pagination-link" href="?p=2">2</a>' if kind == "1" else ""),
        )

    with provider("hatzi-hinam", handler) as source:
        assert len(tuple(source.iter_files())) == 2


def test_explicit_subchain_mismatch_cannot_fall_back_to_a_unique_store_number():
    def handler(request):
        if request.url.path.endswith("getfiles"):
            return httpx.Response(
                200,
                json=[
                    {"fileName": name}
                    for name in (
                        "Stores7290696200003-000-20261031060100-060100.gz",
                        "PriceFull7290696200003-002-007-20261031-060000.gz",
                    )
                ],
            )
        return httpx.Response(200, content=roster("7290696200003"))

    with provider("victory", handler) as source:
        with pytest.raises(SourceError, match="NO_PRICE_FULL"):
            source.list_branches()


def test_deferred_sources_fail_before_network_client_creation(monkeypatch):
    from ingestor.providers import published

    monkeypatch.setattr(published, "BoundedClient", lambda **kw: pytest.fail("client created"))
    with pytest.raises(SourceError, match="SOURCE_DEFERRED"):
        PublishedProvider("carrefour", load_settings({}), monotonic() + 60)


@pytest.mark.parametrize(
    "chain,source_id", [("yochananof", "7290803800003"), ("tiv-taam", "7290873255550")]
)
def test_only_documented_publishers_map_roster_subchain_to_catalog_zero(chain, source_id):
    base = cerberus_handler()

    def handler(request):
        if request.url.path.endswith(".xml"):
            return httpx.Response(200, content=roster(source_id))
        response = base(request)
        if request.url.path == "/file/json/dir":
            payload = response.json()
            for row in payload["aaData"]:
                row["fname"] = (
                    row["fname"].replace("7290058140886", source_id).replace("-001-", "-000-")
                )
            return httpx.Response(200, json=payload)
        return response

    with provider(chain, handler) as source:
        assert all(branch.identity.subchain_id == "000" for branch in source.list_branches())
        assert len(tuple(source.iter_files())) == 2


@pytest.mark.parametrize("ambiguous", [False, True])
def test_missing_filename_subchain_uses_only_a_unique_roster_match(ambiguous):
    def handler(request):
        if request.url.path.endswith("getfiles"):
            return httpx.Response(
                200,
                json=[
                    {"fileName": name}
                    for name in (
                        "Stores7290696200003-000-20261031060100-060100.gz",
                        "PriceFull7290696200003-007-202610310600.gz",
                    )
                ],
            )
        xml = roster("7290696200003")
        if ambiguous:
            xml = xml.replace(
                b"</SubChains>",
                b"<SubChain><SubChainId>002</SubChainId><Stores>"
                b"<Store><StoreId>007</StoreId><StoreType>1</StoreType></Store>"
                b"</Stores></SubChain></SubChains>",
            )
        return httpx.Response(200, content=xml)

    with provider("victory", handler) as source:
        if ambiguous:
            with pytest.raises(SourceError, match="NO_PRICE_FULL"):
                source.list_branches()
        else:
            assert next(source.iter_files()).identity.subchain_id == "001"


def test_roster_and_catalog_download_path_never_writes_files(monkeypatch):
    import builtins
    from pathlib import Path

    original = builtins.open

    def guard(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            pytest.fail("raw download attempted a filesystem write")
        return original(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guard)
    monkeypatch.setattr(Path, "write_bytes", lambda *args, **kwargs: pytest.fail("raw bytes write"))
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: pytest.fail("raw text write"))
    with provider("rami-levy", cerberus_handler()) as source:
        source.list_branches()
        assert source.download(next(source.iter_files())) == b"catalog"
