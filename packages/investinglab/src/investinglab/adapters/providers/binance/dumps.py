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
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from typing import TYPE_CHECKING, Final
from xml.etree import ElementTree as ET

from investinglab.adapters.http import HttpClient
from investinglab.ports.errors import ProviderDataError, UnsupportedRequestError
from investinglab.ports.market_data import RateLimit

if TYPE_CHECKING:
    from collections.abc import Sequence

    import httpx

    from investinglab.adapters.http import RetryPolicy

__all__ = [
    "BUCKET",
    "DUMPS_URL",
    "LISTING_URL",
    "MAX_FILES",
    "MAX_UNZIPPED",
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


def _keys(provider: str, document: str) -> tuple[list[str], bool]:
    """The keys of one page of an S3 listing, and whether more pages follow."""
    if "<!DOCTYPE" in document or "<!ENTITY" in document:
        raise ProviderDataError(provider, "the dump listing declares a DTD: refused")
    try:
        root = ET.fromstring(document)  # noqa: S314 - DTDs and entities refused above
    except ET.ParseError as error:
        raise ProviderDataError(provider, f"unreadable dump listing ({error})") from None
    if root.tag != f"{_S3}ListBucketResult":
        raise ProviderDataError(provider, f"unexpected dump listing ({root.tag})")
    keys = [node.text or "" for node in root.iter(f"{_S3}Key")]
    truncated = (root.findtext(f"{_S3}IsTruncated") or "").strip().lower() == "true"
    return keys, truncated


async def published(
    provider: str,
    listing: HttpClient,
    prefix: str,
    *,
    after: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    page_size: int = LISTING_PAGE,
) -> list[str]:
    """The ZIP files published under ``prefix``, in key order.

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
    found: list[str] = []
    marker = after
    for _ in range(MAX_LISTING_PAGES):
        params: dict[str, str | int] = {"prefix": prefix, "max-keys": page_size}
        if marker is not None:
            params["marker"] = marker
        document = await listing.get_text(f"/{BUCKET}", params)
        keys, truncated = _keys(provider, document)
        for key in keys:
            if until is not None and key > until:
                return found
            if key.startswith(prefix) and key.endswith(".zip"):
                found.append(key)
                if limit is not None and len(found) >= limit:
                    return found
        if not truncated or not keys:
            return found
        marker = keys[-1]
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


async def read_verified(provider: str, dumps: HttpClient, key: str) -> str:
    """Download ``key`` and its checksum, verify it and return the CSV inside.

    Raises:
        ProviderDataError: If the file does not match its checksum or is not one CSV.
        ProviderError: Any failure of the download, translated by the HTTP client.
    """
    archive, checksum = await asyncio.gather(
        dumps.get_bytes(f"/{key}"), dumps.get_bytes(f"/{key}{_CHECKSUM}")
    )
    expected = _expected_digest(provider, key, checksum)
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ProviderDataError(provider, f"{key}: does not match its published SHA-256")
    return _member(provider, key, archive)


async def read_all(provider: str, dumps: HttpClient, keys: Sequence[str]) -> list[str]:
    """The CSV of every file in ``keys``, verified, in the same order.

    Raises:
        UnsupportedRequestError: If they are more than :data:`MAX_FILES`.
        ProviderError: As :func:`read_verified`.
    """
    if len(keys) > MAX_FILES:
        raise UnsupportedRequestError(
            provider, f"{len(keys)} files to download, more than {MAX_FILES}; ask for less"
        )
    gate = asyncio.Semaphore(PARALLEL)

    async def one(key: str) -> str:
        async with gate:
            return await read_verified(provider, dumps, key)

    return list(await asyncio.gather(*(one(key) for key in keys)))
