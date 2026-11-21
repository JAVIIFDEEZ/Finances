"""The cache of published files: kept by version, never outside its folder, never an error."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from investinglab.adapters.storage import PublishedFileCache, UnsafeKeyError

if TYPE_CHECKING:
    from pathlib import Path

KEY = "data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-11-01.zip"


def test_a_file_is_served_only_in_the_version_it_was_saved_with(tmp_path: Path) -> None:
    cache = PublishedFileCache(tmp_path)

    assert cache.load(KEY, "v1") is None
    cache.save(KEY, "v1", b"archive", b"digest  name.zip")

    assert cache.load(KEY, "v1") == (b"archive", b"digest  name.zip")
    assert cache.load(KEY, "v2") is None  # published again: downloaded again
    assert (tmp_path / KEY).read_bytes() == b"archive"  # kept exactly as published
    assert (tmp_path / f"{KEY}.CHECKSUM").read_bytes() == b"digest  name.zip"
    assert not list(tmp_path.rglob("*.tmp"))  # nothing left half-written


def test_saving_again_replaces_the_version(tmp_path: Path) -> None:
    cache = PublishedFileCache(tmp_path)
    cache.save(KEY, "v1", b"old", b"old checksum")

    cache.save(KEY, "v2", b"new", b"new checksum")

    assert cache.load(KEY, "v1") is None
    assert cache.load(KEY, "v2") == (b"new", b"new checksum")


def test_a_discarded_or_unreadable_entry_is_a_miss(tmp_path: Path) -> None:
    cache = PublishedFileCache(tmp_path)
    cache.save(KEY, "v1", b"archive", b"checksum")

    cache.discard(KEY)

    assert cache.load(KEY, "v1") is None
    assert not (tmp_path / KEY).exists()
    cache.save(KEY, "v1", b"archive", b"checksum")
    (tmp_path / f"{KEY}.entry.json").write_text("{not json", encoding="utf-8")
    assert cache.load(KEY, "v1") is None
    cache.save(KEY, "v1", b"archive", b"checksum")
    (tmp_path / KEY).unlink()  # an entry whose archive went missing
    assert cache.load(KEY, "v1") is None
    cache.discard("never/saved.zip")  # forgetting what is not there is fine


def test_a_disk_that_cannot_be_written_never_fails_the_request(tmp_path: Path) -> None:
    blocker = tmp_path / "data"
    blocker.write_text("a file where a folder should be", encoding="utf-8")
    cache = PublishedFileCache(tmp_path)

    cache.save(KEY, "v1", b"archive", b"checksum")  # logged, not raised

    assert cache.load(KEY, "v1") is None


@pytest.mark.parametrize(
    "key",
    [
        "../outside.zip",
        "data/../../outside.zip",
        "/etc/passwd",
        "data//double.zip",
        "data/./here.zip",
        ".hidden.zip",
        "data\\windows.zip",
        "data/sp ace.zip",
        "",
        "a" * 600,
    ],
)
def test_a_key_from_the_listing_never_leaves_the_folder(tmp_path: Path, key: str) -> None:
    cache = PublishedFileCache(tmp_path / "cache")

    with pytest.raises(UnsafeKeyError):
        cache.load(key, "v1")
    with pytest.raises(UnsafeKeyError):
        cache.save(key, "v1", b"x", b"y")
    with pytest.raises(UnsafeKeyError):
        cache.discard(key)
    assert not (tmp_path / "outside.zip").exists()
