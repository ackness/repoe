"""Offline reader for poe2-zh-cn-stats schema-1 raw snapshot inputs.

This module consumes the existing collector's format; it never collects data.
Only the selected English international response is read, not translation sheets
or supplemental pages. Text associations are candidates, not game stat identity.
"""

from collections import defaultdict
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit
import zlib

from RePoE.model.stat_translations import TradeStat


TRADE_EN_URL = "https://www.pathofexile.com/api/trade2/data/stats"
TRADE_CN_URL = "https://poe.game.qq.com/api/trade2/data/stats"
MAX_BODY_BYTES = 16 * 1024 * 1024  # Same response limit as the snapshot collector.
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_GZIP_BYTES = MAX_BODY_BYTES + 64 * 1024


def fingerprint(raw):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _json(raw):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def _canonical(path):
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("Snapshot paths must not contain '..'")
    absolute = path.absolute()
    if absolute.resolve(strict=True) != absolute:
        raise ValueError(f"Snapshot paths must be canonical and contain no symlinks: {path}")
    return absolute


def _read(path, limit):
    path = _canonical(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"Snapshot input must be a regular file: {path}")
    with path.open("rb") as file:
        raw = file.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"Snapshot input exceeds {limit} bytes: {path.name}")
    return raw


def _source_records(manifest):
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Invalid snapshot sources")
    records, files = {}, set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Invalid snapshot source record")
        key, file, url = source.get("key"), source.get("file"), source.get("url")
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", key)
            or key in records
            or not isinstance(file, str)
            or not re.fullmatch(r"raw/[A-Za-z0-9_-]+\.(json|html|txt)\.gz", file)
            or file in files
            or not isinstance(url, str)
            or not url.startswith("https://")
            or not urlsplit(url).netloc
            or not _hash(source.get("sha256"))
            or type(source.get("bytes")) is not int
            or not 0 < source["bytes"] <= MAX_BODY_BYTES
            or type(source.get("status")) is not int
            or source["status"] != 200
            or not isinstance(source.get("fetched_at"), str)
            or not source["fetched_at"]
            or not isinstance(source.get("content_type"), (str, type(None)))
            or not isinstance(source.get("last_modified"), (str, type(None)))
            or not isinstance(source.get("etag"), (str, type(None)))
        ):
            raise ValueError(f"Invalid or duplicate snapshot source: {key}")
        records[key] = source
        files.add(file)
    for key, url in (("trade-en", TRADE_EN_URL), ("trade-cn", TRADE_CN_URL)):
        source = records.get(key)
        if not source or source["url"] != url or source["file"] != f"raw/{key}.json.gz":
            raise ValueError(f"Missing or mismatched official snapshot source: {key}")
    return records


def _catalog_index(raw):
    data = _json(raw)
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise ValueError("Invalid trade catalog result")
    index, branches, groups = defaultdict(list), set(), set()
    non_pseudo = False
    for group in data["result"]:
        if (
            not isinstance(group, dict)
            or not isinstance(group.get("id"), str)
            or not group["id"]
            or group["id"] in groups
            or not isinstance(group.get("entries"), list)
        ):
            raise ValueError("Invalid or duplicate trade catalog group")
        groups.add(group["id"])
        for entry in group["entries"]:
            # Use the existing output model now, before any client/output effects.
            # New API shapes require explicit support, never dropped fields.
            value = TradeStat.model_validate(entry, strict=True)
            if (
                not value.id.startswith(group["id"] + ".")
                or (value.id, value.text) in branches
                or not value.text
                or not value.type.root
            ):
                raise ValueError(f"Invalid or duplicate trade catalog entry: {value.id}")
            branches.add((value.id, value.text))
            non_pseudo |= group["id"] != "pseudo"
            if value.option is not None:
                if not value.option.options or len({o.id for o in value.option.options}) != len(value.option.options):
                    raise ValueError(f"Invalid or duplicate trade options: {value.id}")
                texts = {value.text.replace("#", option.text) for option in value.option.options}
            else:
                texts = {value.text}
            for text in sorted(texts):
                index[text].append(entry)
    if not non_pseudo:
        raise ValueError("Empty non-pseudo trade catalog")
    return {text: sorted(entries, key=lambda entry: (entry["id"], entry["text"])) for text, entries in index.items()}


@dataclass(frozen=True)
class TradeSnapshot:
    index: dict
    provenance: dict


def load_trade_snapshot(directory, *, expected_sha256=None, language="English", realm="international"):
    """Validate a local snapshot before the caller opens a client or output.

    expected_sha256 is an optional trusted SHA-256 of manifest.json's exact bytes.
    Internal checksums alone bind bytes, not their authenticity or game accuracy.
    """
    if language != "English" or realm != "international":
        raise ValueError("Trade snapshots currently require English and the international realm")
    if not str(directory):
        raise ValueError("Trade snapshot directory must not be empty")
    if expected_sha256 is not None and not _hash(expected_sha256):
        raise ValueError("Expected manifest SHA-256 must be 64 lowercase hexadecimal characters")
    directory = _canonical(directory)
    if not directory.is_dir():
        raise ValueError("Trade snapshot path must be a directory containing manifest.json and raw/")
    manifest_raw = _read(directory / "manifest.json", MAX_MANIFEST_BYTES)
    manifest_hash = fingerprint(manifest_raw)
    if expected_sha256 is not None and manifest_hash["sha256"] != expected_sha256:
        raise ValueError("Trade snapshot manifest SHA-256 mismatch")
    manifest = _json(manifest_raw)
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or not isinstance(manifest.get("id"), str)
        or not re.fullmatch(r"[0-9TZ]+", manifest["id"])
        or not isinstance(manifest.get("captured_at"), str)
        or not manifest["captured_at"]
        or "game_patch" not in manifest
        or not isinstance(manifest["game_patch"], (str, type(None)))
        or not isinstance(manifest.get("pages"), list)
        or not _hash(manifest.get("config_sha256"))
    ):
        raise ValueError("Invalid schema-1 trade snapshot manifest")
    config = manifest.get("config")
    if not isinstance(config, dict) or config.get("trade") != {"en": TRADE_EN_URL, "cn": TRADE_CN_URL}:
        raise ValueError("Mismatched snapshot trade language/realm configuration")
    source = _source_records(manifest)["trade-en"]
    compressed = _read(directory / source["file"], MAX_GZIP_BYTES)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as file:
            body = file.read(MAX_BODY_BYTES + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError(f"Invalid trade snapshot gzip: {error}") from error
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("Trade snapshot body exceeds response size limit")
    body_hash = fingerprint(body)
    if body_hash != {"sha256": source["sha256"], "bytes": source["bytes"]}:
        raise ValueError("Trade snapshot response checksum/size mismatch")
    index = _catalog_index(body)
    return TradeSnapshot(
        index=index,
        provenance={
            "schema_version": 1,
            "snapshot_id": manifest["id"],
            "captured_at": manifest["captured_at"],
            "game_patch": manifest["game_patch"],
            "manifest": manifest_hash,
            "expected_manifest_sha256": expected_sha256,
            "source": source,
            "compressed_response": fingerprint(compressed),
            "response": body_hash,
            "language": language,
            "realm": realm,
        },
    )
