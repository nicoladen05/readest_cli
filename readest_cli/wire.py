# Adapted from readest/readest apps/readest-calibre-plugin/wire.py.
# Copyright (C) 2026 Bilingify LLC
# Modified in 2026 for readest-cli.
# SPDX-License-Identifier: AGPL-3.0-only

"""EPUB metadata to Readest wire records and upload planning."""

import json
from datetime import datetime, timezone

from .api import meta_hash

CLOUD_BOOKS_SUBDIR = "Readest/Books"
COVER_FILE_NAME = "cover.png"


def book_file_name(file_hash):
    return "%s/%s/%s.epub" % (CLOUD_BOOKS_SUBDIR, file_hash, file_hash)


def cover_file_name(file_hash):
    return "%s/%s/%s" % (CLOUD_BOOKS_SUBDIR, file_hash, COVER_FILE_NAME)


def cloud_book_hashes(files):
    marker = CLOUD_BOOKS_SUBDIR + "/"
    hashes = set()
    for record in files or []:
        key = record.get("file_key") or ""
        index = key.find(marker)
        if index < 0:
            continue
        book_hash, _, name = key[index + len(marker) :].partition("/")
        if book_hash and name and name != COVER_FILE_NAME:
            hashes.add(book_hash)
    return hashes


def _clean(value):
    return value.replace("\x00", "") if isinstance(value, str) else value


def build_metadata(book):
    authors = [_clean(a) for a in book.get("authors") or [] if a]
    identifiers = [_clean(i) for i in book.get("identifiers") or [] if i]
    metadata = {
        "title": _clean(book.get("title")) or "",
        "author": authors[0] if len(authors) == 1 else authors,
    }
    languages = book.get("languages") or []
    if languages:
        metadata["language"] = languages[0] if len(languages) == 1 else languages
    if identifiers:
        metadata["identifier"] = identifiers[0]
        if len(identifiers) > 1:
            metadata["altIdentifier"] = identifiers
    optional = {
        "publisher": _clean(book.get("publisher")),
        "published": _clean(book.get("pubdate")),
        "description": _clean(book.get("comments")),
        "subject": [_clean(t) for t in book.get("tags") or []] or None,
        "isbn": _clean(book.get("isbn")),
        # The marker distinguishes a changed source file when identity is
        # matched through EPUB identifiers instead of the content hash.
        "readestCliSourceHash": book.get("source_hash"),
    }
    for key, value in optional.items():
        if value not in (None, "", []):
            metadata[key] = value
    return metadata


def build_wire_book(book, file_hash, now_ms):
    title = _clean(book.get("title")) or ""
    authors = [_clean(a) for a in book.get("authors") or [] if a]
    identifiers = [_clean(i) for i in book.get("identifiers") or [] if i]
    return {
        "hash": file_hash,
        "bookHash": file_hash,
        "metaHash": meta_hash(title, authors, identifiers),
        "format": "EPUB",
        "title": title,
        "sourceTitle": title,
        "author": ", ".join(authors),
        "tags": [_clean(t) for t in book.get("tags") or []],
        "metadata": build_metadata(book),
        "createdAt": now_ms,
        "updatedAt": now_ms,
    }


def iso_to_ms(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def ms_to_iso(value):
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def parse_row_metadata(row):
    raw = row.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except ValueError:
            pass
    return {}


def _identifier_keys(value):
    if isinstance(value, dict):
        text = str(value.get("value") or "").strip().lower()
        scheme = str(value.get("scheme") or "").strip().lower()
        return {text, "%s:%s" % (scheme, text)} - {"", ":"}
    text = str(value or "").strip().lower()
    if not text:
        return set()
    normalized = text.rsplit(":", 1)[-1] if "urn:" in text else text.split(":", 1)[-1]
    return {text, normalized}


def metadata_identifiers(metadata):
    values = []
    for key in ("identifier", "altIdentifier", "isbn"):
        value = (metadata or {}).get(key)
        values.extend(value if isinstance(value, list) else [value])
    keys = set()
    for value in values:
        keys.update(_identifier_keys(value))
    return keys


def row_source_hash(row):
    metadata = parse_row_metadata(row)
    return (
        metadata.get("readestCliSourceHash")
        or metadata.get("calibreSourceHash")
        or row.get("book_hash")
    )


def preserve_server_metadata(wire, server_row):
    """Keep metadata fields this EPUB-only client does not understand."""
    if server_row:
        wire["metadata"] = {**parse_row_metadata(server_row), **wire["metadata"]}
    return wire


def _row_matches_wire(row, wire):
    return (
        (row.get("title") or "") == wire["title"]
        and (row.get("author") or "") == wire["author"]
        and (row.get("tags") or []) == (wire.get("tags") or [])
        and parse_row_metadata(row) == wire["metadata"]
    )


def _prefer_row(row, current):
    row_live, current_live = not row.get("deleted_at"), not current.get("deleted_at")
    if row_live != current_live:
        return row_live
    return (iso_to_ms(row.get("updated_at")) or 0) > (
        iso_to_ms(current.get("updated_at")) or 0
    )


def index_rows_by_identifier(rows):
    best = {}
    for row in rows:
        for identifier in metadata_identifiers(parse_row_metadata(row)):
            current = best.get(identifier)
            if current is None or _prefer_row(row, current):
                best[identifier] = row
    return best


def pick_server_row(hash_row, identifier_rows):
    rows = [hash_row] + list(identifier_rows)
    for row in rows:
        if row is not None and not row.get("deleted_at"):
            return row
    return next((row for row in rows if row is not None), None)


def plan_push(server_row, wire, cover_hash, source_hash, blob_present=True):
    if server_row is None:
        return {"action": "new", "upload_cover": bool(cover_hash)}
    present = blob_present(server_row["book_hash"]) if callable(blob_present) else blob_present
    if not server_row.get("uploaded_at") or row_source_hash(server_row) != source_hash or not present:
        return {"action": "replace", "upload_cover": bool(cover_hash)}
    cover_changed = bool(cover_hash) and cover_hash != server_row.get("cover_hash")
    changed = not _row_matches_wire(server_row, wire) or bool(server_row.get("deleted_at"))
    return {"action": "update" if changed or cover_changed else "skip", "upload_cover": cover_changed}


def tombstone_record(row, now_ms):
    return {
        "hash": row["book_hash"],
        "bookHash": row["book_hash"],
        "metaHash": row.get("meta_hash"),
        "format": row.get("format"),
        "title": row.get("title") or "",
        "author": row.get("author") or "",
        "createdAt": iso_to_ms(row.get("created_at")) or now_ms,
        "updatedAt": now_ms,
        "deletedAt": now_ms,
    }


def merge_for_push(wire, server_row, now_ms, uploaded_at_ms=None, cover_hash=None):
    """Preserve fields that transformBookToDB otherwise turns into nulls."""
    record = dict(wire)
    record["updatedAt"] = now_ms
    record["deletedAt"] = None
    row = server_row or {}
    record["createdAt"] = iso_to_ms(row.get("created_at")) or wire["createdAt"]
    for source, target in (("group_id", "groupId"), ("group_name", "groupName")):
        if row.get(source) is not None:
            record[target] = row[source]
    if row.get("group_updated_at"):
        record["groupUpdatedAt"] = iso_to_ms(row["group_updated_at"])
    if row.get("progress") is not None:
        record["progress"] = row["progress"]
    if row.get("reading_status") is not None:
        record["readingStatus"] = row["reading_status"]
        record["readingStatusUpdatedAt"] = iso_to_ms(row.get("reading_status_updated_at"))
    record["uploadedAt"] = (
        uploaded_at_ms if uploaded_at_ms is not None else iso_to_ms(row.get("uploaded_at"))
    )
    if cover_hash:
        record["coverHash"] = cover_hash
        record["coverUpdatedAt"] = now_ms
    elif row.get("cover_hash"):
        record["coverHash"] = row["cover_hash"]
        record["coverUpdatedAt"] = iso_to_ms(row.get("cover_updated_at"))
    record["metadataUpdatedAt"] = (
        now_ms
        if server_row is None or not _row_matches_wire(server_row, wire)
        else iso_to_ms(row.get("metadata_updated_at"))
    )
    return record
