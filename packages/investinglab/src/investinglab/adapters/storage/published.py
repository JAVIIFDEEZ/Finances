"""Files published with their checksum, kept on disk once verified (ADR-0043).

Some sources publish their history as files that do not change once out: Binance's monthly
and daily dumps, each with a ``.CHECKSUM`` holding its SHA-256. Reading a year of daily
positioning means downloading 365 of them; the second time, nothing has changed. This cache
keeps each file *exactly as published*, with its checksum file and the version the source's
listing gave it (an S3 ``ETag``), so that:

* **It is still verified.** The cache does not trust itself: whoever reads an entry checks
  the archive against the published checksum again, as if it had just been downloaded. A
  damaged copy on disk is told apart and downloaded again.
* **A republished file is noticed.** An entry serves only the version it was saved with; if
  the listing names another one, the file is downloaded again. A file whose listing gives no
  version is never cached.
* **It never writes outside its folder.** Keys come from a remote listing: a key that is not
  a plain relative path (``..``, an absolute path, odd characters) is refused.
* **It is only an optimisation.** Entries are written atomically (a temporary file renamed
  over the old one); a read that fails is a miss and a write that fails is logged, never an
  error of the request.

Removing the folder is always safe: the files are downloaded again when next needed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Final

from investinglab.config.logging import get_logger

__all__ = ["PublishedFileCache", "UnsafeKeyError"]

log = get_logger(__name__)

_SAFE_KEY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]*(/[A-Za-z0-9][A-Za-z0-9._\-]*)*")
_MAX_KEY: Final = 512
_FORMAT: Final = 1
"""Version of the entry layout; an entry of another format is a miss."""


class UnsafeKeyError(ValueError):
    """A key that is not a plain relative path inside the cache."""


class PublishedFileCache:
    """Verified files of a source, by key and version, under ``root``.

    An entry is three files next to each other: the archive (named as its key), its
    checksum file as published (``<key>.CHECKSUM``) and what the cache knows of it
    (``<key>.entry.json``: the version and the layout). The entry is written last, so an
    archive without it is never served.

    Args:
        root: Folder of this source's files (created when the first one is saved).
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        """Folder of the cached files."""
        return self._root

    def load(self, key: str, version: str) -> tuple[bytes, bytes] | None:
        """The archive and the checksum file of ``key`` if saved with ``version``.

        Returns ``None`` when there is no entry, it holds another version or it cannot be
        read. The caller still verifies the archive against the checksum.

        Raises:
            UnsafeKeyError: If ``key`` is not a plain relative path.
        """
        archive, checksum, entry = self._paths(key)
        try:
            known = json.loads(entry.read_text(encoding="utf-8"))
            if known != {"format": _FORMAT, "version": version}:
                return None
            return archive.read_bytes(), checksum.read_bytes()
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            log.warning("published_cache_unreadable", key=key, error=str(error))
            return None

    def save(self, key: str, version: str, archive: bytes, checksum: bytes) -> None:
        """Keep a verified archive and its checksum file as version ``version`` of ``key``.

        Never raises for the disk: a failed write is logged and the entry left absent.

        Raises:
            UnsafeKeyError: If ``key`` is not a plain relative path.
        """
        archive_path, checksum_path, entry_path = self._paths(key)
        entry = json.dumps({"format": _FORMAT, "version": version}).encode("utf-8")
        try:
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            entry_path.unlink(missing_ok=True)  # never an entry over a half-written archive
            _write_atomically(archive_path, archive)
            _write_atomically(checksum_path, checksum)
            _write_atomically(entry_path, entry)
        except OSError as error:
            log.warning("published_cache_write_failed", key=key, error=str(error))

    def discard(self, key: str) -> None:
        """Forget ``key`` (a copy that did not match its checksum).

        Raises:
            UnsafeKeyError: If ``key`` is not a plain relative path.
        """
        for path in reversed(self._paths(key)):  # the entry first: the archive is then unused
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                log.warning("published_cache_discard_failed", key=key, error=str(error))

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        if len(key) > _MAX_KEY or not _SAFE_KEY.fullmatch(key) or ".." in key.split("/"):
            raise UnsafeKeyError(f"not a plain relative key: {key[:80]!r}")
        archive = self._root / key
        return (
            archive,
            archive.with_name(f"{archive.name}.CHECKSUM"),
            archive.with_name(f"{archive.name}.entry.json"),
        )


def _write_atomically(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` through a temporary file renamed over it."""
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
