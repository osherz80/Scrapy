"""Bounded portal inventories with publisher roster classification and identity."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

from ..chains import DEFERRED_CHAIN_IDS
from ..config import Settings
from ..logging.types import Logger
from .http import BoundedClient
from .roster import parse_filename, parse_roster
from .stream import SourceError, decompress
from .types import FileKind, PublishedFile, identifier_key

# Audited public publisher identifiers and public, passwordless Cerberus logins.
# No private credential or environment-file lookup is used by these portals.
_SOURCES = {
    "rami-levy": ("7290058140886", "cerberus", "RamiLevi"),
    "yochananof": ("7290803800003", "cerberus", "yohananof"),
    "osher-ad": ("7290103152017", "cerberus", "osherad"),
    "tiv-taam": ("7290873255550", "cerberus", "TivTaam"),
    "keshet-teamim": ("7290785400000", "cerberus", "Keshet"),
    "victory": ("7290696200003", "laib", None),
    "mahsanei-hashuk": ("7290661400001", "laib", None),
    "hatzi-hinam": ("7290700100008", "hatzi", None),
}
_HOSTS = {
    "cerberus": "url.publishedprices.co.il",
    "laib": "laibcatalog.co.il",
    "hatzi": "shop.hazi-hinam.co.il",
}


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.csrf, self.links, self.pages = None, [], set()

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "meta" and fields.get("name", "").lower() == "csrftoken":
            self.csrf = fields.get("content")
        if tag == "a":
            href = fields.get("href", "")
            self.links.append(href)
            if "pagination-link" in fields.get("class", "").split():
                page = parse_qs(urlsplit(href).query).get("p", [])
                if len(page) != 1 or not page[0].isascii() or not page[0].isdecimal():
                    raise SourceError("INCOMPLETE_LISTING")
                self.pages.add(int(page[0]))


class PublishedProvider:
    def __init__(
        self,
        chain: str,
        settings: Settings,
        deadline: float,
        logger: Logger | None = None,
        *,
        client=None,
    ):
        if chain in DEFERRED_CHAIN_IDS:
            raise SourceError("SOURCE_DEFERRED")
        if chain not in _SOURCES or chain not in settings.enabled_chains:
            raise SourceError("CHAIN_DISABLED")
        self.chain = chain
        self.source_chain_id, self._family, self._username = _SOURCES[chain]
        self._base = "https://" + _HOSTS[self._family]
        self._limit = settings.provider_max_decompressed_bytes
        self._client = (
            client
            if client is not None
            else BoundedClient(
                allowed_hosts=frozenset({_HOSTS[self._family]}),
                allow_azure=self._family == "hatzi",
                timeout_seconds=settings.provider_timeout_seconds,
                max_bytes=self._limit,
                deadline=deadline,
                logger=logger,
            )
        )
        self._client.deadline = min(self._client.deadline, deadline)
        self._csrf, self._branches, self._files = None, None, ()
        self.roster_filename = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._client.close()

    def _login(self):
        page = _Page()
        page.feed(self._client.get(self._base + "/login").text)
        if not page.csrf or len(page.csrf) > 1024:
            raise SourceError("AUTH_FAILED")
        response = self._client.post(
            self._base + "/login/user",
            data={
                "r": "",
                "username": self._username,
                "password": "",
                "Submit": "Sign in",
                "csrftoken": page.csrf,
            },
        )
        page = _Page()
        page.feed(response.text)
        if response.url.path.startswith("/login") or not page.csrf or len(page.csrf) > 1024:
            raise SourceError("AUTH_FAILED")
        self._csrf = page.csrf

    def _cerberus(self, search):
        if self._csrf is None:
            self._login()
        found, seen, expected = [], set(), None
        while True:
            response = self._client.post(
                self._base + "/file/json/dir",
                data={
                    "cd": "/",
                    "sSearch": search,
                    "iDisplayStart": len(found),
                    "iDisplayLength": 1000,
                    "csrftoken": self._csrf,
                },
            )
            try:
                payload = response.json()
                rows = payload["aaData"]
                for count in (payload["iTotalDisplayRecords"], payload["iTotalRecords"]):
                    if not (
                        type(count) is int
                        or (isinstance(count, str) and count.isascii() and count.isdecimal())
                    ):
                        raise ValueError
                total = int(payload["iTotalDisplayRecords"])
                all_total = int(payload["iTotalRecords"])
                if not isinstance(rows, list) or not 0 <= total <= all_total:
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                raise SourceError("INCOMPLETE_LISTING") from None
            if expected is None:
                expected = total
            if (
                total != expected
                or len(found) + len(rows) > total
                or (not rows and len(found) < total)
            ):
                raise SourceError("INCOMPLETE_LISTING")
            for row in rows:
                name = row.get("fname") if isinstance(row, dict) else None
                if (
                    not isinstance(name, str)
                    or not name
                    or name in seen
                    or row.get("type") != "file"
                ):
                    raise SourceError("INCOMPLETE_LISTING")
                seen.add(name)
                found.append((name, self._base + "/file/d/" + quote(name, safe="")))
            if len(found) == total:
                return found

    def _laib(self):
        try:
            rows = self._client.get(
                self._base + "/webapi/api/getfiles", params={"edi": self.source_chain_id}
            ).json()
        except ValueError:
            raise SourceError("INCOMPLETE_LISTING") from None
        if not isinstance(rows, list):
            raise SourceError("INCOMPLETE_LISTING")
        found, seen = [], set()
        for row in rows:
            name = row.get("fileName") if isinstance(row, dict) else None
            if not isinstance(name, str) or not name or name in seen:
                raise SourceError("INCOMPLETE_LISTING")
            seen.add(name)
            found.append(
                (name, f"{self._base}/webapi/{self.source_chain_id}/{quote(name, safe='')}")
            )
        return found

    def _hatzi(self, kind):
        found, seen, page, last = [], set(), 1, 1
        while page <= last:
            document = _Page()
            document.feed(
                self._client.get(self._base + "/Prices", params={"t": kind, "p": page}).text
            )
            if page not in document.pages or any(value < 1 for value in document.pages):
                raise SourceError("INCOMPLETE_LISTING")
            last = max(last, max(document.pages))
            this_page = {}
            for url in document.links:
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or not parsed.hostname.endswith(".blob.core.windows.net")
                ):
                    continue
                name = parsed.path.rsplit("/", 1)[-1]
                if parse_filename(name) is None:
                    continue
                if name in this_page and this_page[name] != url:
                    raise SourceError("INCOMPLETE_LISTING")
                this_page[name] = url
            if not this_page:
                raise SourceError("INCOMPLETE_LISTING")
            for name, url in this_page.items():
                if name in seen:
                    raise SourceError("INCOMPLETE_LISTING")
                seen.add(name)
                found.append((name, url))
            page += 1
        return found

    def _inventory(self):
        if self._branches is not None:
            return
        if self._family == "cerberus":
            listed = self._cerberus("Stores") + self._cerberus("PriceFull")
        elif self._family == "laib":
            listed = self._laib()
        else:
            listed = self._hatzi("3") + self._hatzi("1")
        refs = []
        for name, url in listed:
            ref = parse_filename(name)
            if ref is None:
                if name.lower().startswith(
                    (
                        "pricefull" + self.source_chain_id,
                        "stores" + self.source_chain_id,
                        "storesfull" + self.source_chain_id,
                    )
                ):
                    raise SourceError("INVALID_FILENAME")
                continue
            if ref.source_chain_id == self.source_chain_id:
                refs.append((ref, name, url))
        stores = [ref for ref in refs if ref[0].kind == FileKind.STORES]
        if not stores:
            raise SourceError("NO_STORES")
        if any(ref[0].published_at is None for ref in stores):
            raise SourceError("MISSING_SOURCE_TIME")
        latest = max(stores, key=lambda ref: (ref[0].published_at, ref[1]))
        xml = decompress(self._client.get(latest[2]).content, limit=self._limit)
        # Verified roster->catalog subchain differences, not generic fallbacks.
        aliases = {"1": "000"} if self.chain in ("yochananof", "tiv-taam") else {}
        branches = parse_roster(
            xml,
            chain_id=self.chain,
            source_chain_id=self.source_chain_id,
            subchain_aliases=aliases,
            max_bytes=self._limit,
        )
        by_key = {
            (identifier_key(b.identity.subchain_id), identifier_key(b.identity.store_id)): b
            for b in branches
        }
        by_store = {}
        for branch in branches:
            by_store.setdefault(identifier_key(branch.identity.store_id), []).append(branch)
        files = []
        for ref, name, url in refs:
            if ref.kind != FileKind.PRICE_FULL:
                continue
            store = identifier_key(ref.store_id)
            if ref.subchain_id is None:
                matches = by_store.get(store, [])
                branch = matches[0] if len(matches) == 1 else None
            else:
                branch = by_key.get((identifier_key(ref.subchain_id), store))
            if branch is not None:
                files.append(
                    PublishedFile(branch.identity, FileKind.PRICE_FULL, name, url, ref.published_at)
                )
        if not files:
            raise SourceError("NO_PRICE_FULL")
        self._branches, self._files, self.roster_filename = branches, tuple(files), latest[1]

    def list_branches(self):
        self._inventory()
        return self._branches

    def iter_files(self):
        self._inventory()
        return iter(self._files)

    def download(self, ref: PublishedFile) -> bytes:
        if ref not in self._files:
            raise SourceError("UNLISTED_FILE")
        return self._client.get(ref.source_url).content
