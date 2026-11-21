"""Binance's public data dumps (``data.binance.vision``): listing, verified download, unzip.

Binance publishes its market data as daily and monthly ZIP files, each with a ``.CHECKSUM``
file holding its SHA-256. They are served from ``data.binance.vision`` and listed by the S3
bucket behind it. The listing says which files exist, so a file that is not there is told
from a contract Binance does not have, and only the files in a range are downloaded.

What this module guarantees:

* **Integrity.** Every file is checked against its published SHA-256 before it is read; a
  file that does not match is refused, never used.
* **Bounded work.** At most :data:`MAX_FILES` files per request and :data:`MAX_UNZIPPED`
  bytes per file once uncompressed (a damaged or hostile archive cannot fill the memory).
* **Safe listing.** The bucket answers XML; a document that declares a DTD or entities is
  refused before it is parsed, which rules out entity expansion attacks.
* **Downloaded once.** With a :class:`~investinglab.adapters.storage.PublishedFileCache`, a
  verified file is kept with the version the listing gives it (its ``ETag``) and read from
  disk while the listing names that version, verified again against its checksum
  (ADR-0043). Only the listing, one call, goes to the network.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree as ET

from investinglab.adapters.http import HttpClient
from investinglab.config.logging import get_logger
from investinglab.ports.errors import ProviderDataError, UnsupportedRequestError
from investinglab.ports.market_data import RateLimit

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from investinglab.adapters.http import RetryPolicy
    from investinglab.adapters.storage.published import PublishedFileCache

__all__ = [
    "BUCKET",
    "DUMPS_URL",
    "LISTING_URL",
    "MAX_FILES",
    "MAX_UNZIPPED",
    "Listed",
    "dumps_client",
    "listing_client",
    "published",
    "read_all",
    "read_verified",
]

DUMPS_URL: Final = "https://data.binance.vision"
LISTING_URL: Final = "https://s3-ap-northeast-1.amazonaws.com"
BUCKET: Final = "data.binance.vision"

MAX_FILES: Final = 160
"""Most files per request: thirteen years of monthly files, or five months of daily ones."""

MAX_UNZIPPED: Final = 64 * 1024 * 1024
"""Largest file accepted once uncompressed (a day of 5-minute metrics is about 36 kB)."""

LISTING_PAGE: Final = 1_000
"""Most keys the bucket lists per call."""

MAX_LISTING_PAGES: Final = 10

PARALLEL: Final = 6
"""Files downloaded at once."""

DUMPS_LIMITS: Final = (RateLimit(20, 1.0),)
LISTING_LIMITS: Final = (RateLimit(5, 1.0),)

_S3: Final = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_CHECKSUM: Final = ".CHECKSUM"

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Listed:
    """A ZIP file the bucket lists.

    Attributes:
        key: Its path in the bucket (``data/futures/um/monthly/fundingRate/...zip``).
        version: The ``ETag`` the listing gives it: another one means the file was
            published again. ``None`` if the listing gives none (then it is never cached).
    """

    key: str
    version: str | None = None


def dumps_client(
    provider: str,
    *,
    timeout: float = 60.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for the files of ``data.binance.vision``."""
    return HttpClient(
        provider,
        base_url=DUMPS_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=DUMPS_LIMITS,
        transport=transport,
    )


def listing_client(
    provider: str,
    *,
    timeout: float = 30.0,
    retry: RetryPolicy | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpClient:
    """An HTTP client for the listing of the bucket behind ``data.binance.vision``."""
    return HttpClient(
        provider,
        base_url=LISTING_URL,
        timeout=timeout,
        retry=retry,
        rate_limits=LISTING_LIMITS,
        transport=transport,
    )


def _entries(provider: str, document: str) -> tuple[list[Listed], bool]:
    """The keys of one page of an S3 listing with their versions, and whether more follow."""
    if "<!DOCTYPE" in document or "<!ENTITY" in document:
        raise ProviderDataError(provider, "the dump listing declares a DTD: refused")
    try:
        root = ET.fromstring(document)  # noqa: S314 - DTDs and entities refused above
    except ET.ParseError as error:
        raise ProviderDataError(provider, f"unreadable dump listing ({error})") from None
    if root.tag != f"{_S3}ListBucketResult":
        raise ProviderDataError(provider, f"unexpected dump listing ({root.tag})")
    entries = []
    for node in root.iter(f"{_S3}Contents"):
        etag = (node.findtext(f"{_S3}ETag") or "").strip().strip('"')
        entries.append(Listed(node.findtext(f"{_S3}Key") or "", etag or None))
    truncated = (root.findtext(f"{_S3}IsTruncated") or "").strip().lower() == "true"
    return entries, truncated


async def published(
    provider: str,
    listing: HttpClient,
    prefix: str,
    *,
    after: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    page_size: int = LISTING_PAGE,
) -> list[Listed]:
    """The ZIP files published under ``prefix``, in key order, with their versions.

    Args:
        provider: Provider slug, for errors.
        listing: Client of the bucket listing.
        prefix: Folder listed (``data/futures/um/monthly/fundingRate/BTCUSDT/``).
        after: List only the keys after this one (the bucket's ``marker``).
        until: Stop once the keys pass this one (they are sorted).
        limit: Stop once this many files are found (``1`` asks whether there is any).
        page_size: Keys per call.

    Raises:
        UnsupportedRequestError: If the listing needs more than :data:`MAX_LISTING_PAGES`
            calls.
        ProviderDataError: If a page is not a bucket listing.
    """
    found: list[Listed] = []
    marker = after
    for _ in range(MAX_LISTING_PAGES):
        params: dict[str, str | int] = {"prefix": prefix, "max-keys": page_size}
        if marker is not None:
            params["marker"] = marker
        document = await listing.get_text(f"/{BUCKET}", params)
        entries, truncated = _entries(provider, document)
        for entry in entries:
            if until is not None and entry.key > until:
                return found
            if entry.key.startswith(prefix) and entry.key.endswith(".zip"):
                found.append(entry)
                if limit is not None and len(found) >= limit:
                    return found
        if not truncated or not entries:
            return found
        marker = entries[-1].key
    raise UnsupportedRequestError(provider, f"{prefix}: too many files to list; ask for less")


def _member(provider: str, key: str, archive: bytes) -> str:
    """The single CSV inside ``archive``, as text."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            members = [info for info in opened.infolist() if not info.is_dir()]
            if len(members) != 1 or not members[0].filename.endswith(".csv"):
                names = [info.filename for info in members]
                raise ProviderDataError(provider, f"{key}: expected one CSV, found {names}")
            member = members[0]
            if member.file_size > MAX_UNZIPPED:
                raise ProviderDataError(
                    provider, f"{key}: {member.file_size} bytes uncompressed, over the limit"
                )
            with opened.open(member) as handle:
                content = handle.read(MAX_UNZIPPED + 1)
    except zipfile.BadZipFile as error:
        raise ProviderDataError(provider, f"{key}: not a ZIP file ({error})") from None
    if len(content) > MAX_UNZIPPED:
        raise ProviderDataError(provider, f"{key}: larger than declared once uncompressed")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        raise ProviderDataError(provider, f"{key}: the CSV is not UTF-8") from None


def _expected_digest(provider: str, key: str, checksum: bytes) -> str:
    """The SHA-256 a ``.CHECKSUM`` file publishes for ``key``."""
    try:
        digest, name = checksum.decode("ascii").split()
    except (UnicodeDecodeError, ValueError):
        raise ProviderDataError(provider, f"{key}: unreadable checksum file") from None
    if name != key.rsplit("/", 1)[-1] or len(digest) != 64:  # noqa: PLR2004 - SHA-256 in hex
        raise ProviderDataError(provider, f"{key}: the checksum file is for {name}")
    return digest.lower()


def _verified(provider: str, key: str, archive: bytes, checksum: bytes) -> str:
    """The CSV inside ``archive`` once it matches its published SHA-256."""
    expected = _expected_digest(provider, key, checksum)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ProviderDataError(provider, f"{key}: does not match its published SHA-256")
    return _member(provider, key, archive)


async def _cached(provider: str, cache: PublishedFileCache, key: str, version: str) -> str | None:
    """The CSV of a kept copy of ``key``, verified again; ``None`` if there is none."""
    stored = await asyncio.to_thread(cache.load, key, version)
    if stored is None:
        return None
    try:
        return _verified(provider, key, *stored)
    except ProviderDataError as error:
        # A copy damaged on disk is downloaded again, never read.
        log.warning("dump_cache_damaged", provider=provider, key=key, error=str(error))
        await asyncio.to_thread(cache.discard, key)
        return None


async def read_verified(
    provider: str,
    dumps: HttpClient,
    key: str,
    *,
    version: str | None = None,
    cache: PublishedFileCache | None = None,
) -> str:
    """Download ``key`` and its checksum, verify it and return the CSV inside.

    With a ``cache`` and the listing's ``version``, a copy kept with that version is read
    (and verified) instead, and a downloaded file is kept once verified.

    Raises:
        ProviderDataError: If the file does not match its checksum or is not one CSV.
        ProviderError: Any failure of the download, translated by the HTTP client.
    """
    if cache is not None and version is not None:
        found = await _cached(provider, cache, key, version)
        if found is not None:
            return found
    archive, checksum = await asyncio.gather(
        dumps.get_bytes(f"/{key}"), dumps.get_bytes(f"/{key}{_CHECKSUM}")
    )
    text = _verified(provider, key, archive, checksum)
    if cache is not None and version is not None:
        await asyncio.to_thread(cache.save, key, version, archive, checksum)
    return text


async def read_all(
    provider: str,
    dumps: HttpClient,
    files: Sequence[Listed],
    *,
    cache: PublishedFileCache | None = None,
) -> list[str]:
    """The CSV of every listed file, verified, in the same order.

    Raises:
        UnsupportedRequestError: If they are more than :data:`MAX_FILES`.
        ProviderError: As :func:`read_verified`.
    """
    if len(files) > MAX_FILES:
        raise UnsupportedRequestError(
            provider, f"{len(files)} files to download, more than {MAX_FILES}; ask for less"
        )
    gate = asyncio.Semaphore(PARALLEL)

    async def one(listed: Listed) -> str:
        async with gate:
            return await read_verified(
                provider, dumps, listed.key, version=listed.version, cache=cache
            )

    return list(await asyncio.gather(*(one(listed) for listed in files)))
