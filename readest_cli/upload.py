# Copyright (C) 2026 readest-cli contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""Programmatic EPUB upload service. This module does not print."""

import io
import os
import time

from .api import partial_md5, partial_md5_bytes
from .epub import extract_epub
from .wire import (
    book_file_name,
    build_wire_book,
    cloud_book_hashes,
    cover_file_name,
    index_rows_by_identifier,
    merge_for_push,
    metadata_identifiers,
    ms_to_iso,
    pick_server_row,
    plan_push,
    preserve_server_metadata,
    tombstone_record,
)

DUMMY_HASH = "0" * 32


class ReadestLibrary:
    """High-level library API backed by a configured ``ReadestClient``."""

    def __init__(self, api):
        self.api = api

    def list_books(self):
        return [
            row
            for row in self.api.pull_books()
            if row.get("book_hash") != DUMMY_HASH and not row.get("deleted_at")
        ]

    def upload_book(self, path):
        rows = [row for row in self.api.pull_books() if row.get("book_hash") != DUMMY_HASH]
        return _UploadState(self.api, rows).upload(path)

    def upload_books(self, paths):
        """Upload a batch, returning a result (including failures) per path."""
        rows = [row for row in self.api.pull_books() if row.get("book_hash") != DUMMY_HASH]
        state = _UploadState(self.api, rows)
        results = []
        for path in paths:
            try:
                results.append(state.upload(path))
            except Exception as error:
                results.append({"status": "failed", "path": os.fspath(path), "error": str(error)})
        return results


class _UploadState:
    def __init__(self, api, rows):
        self.api = api
        self.by_hash = {row["book_hash"]: row for row in rows if row.get("book_hash")}
        self.by_identifier = index_rows_by_identifier(rows)
        self.blob_cache = {}

    def _blob_present(self, book_hash):
        if book_hash not in self.blob_cache:
            self.blob_cache[book_hash] = book_hash in cloud_book_hashes(
                self.api.list_files(book_hash)
            )
        return self.blob_cache[book_hash]

    def _upload(self, name, stream, size, book_hash):
        result = self.api.get_upload_url(name, size, book_hash)
        upload_url = result.get("uploadUrl") if isinstance(result, dict) else None
        if not upload_url:
            raise ValueError("Readest did not return an upload URL")
        self.api.put_file(upload_url, stream, size)

    def _delete_files(self, book_hash):
        try:
            for item in self.api.list_files(book_hash):
                if item.get("file_key"):
                    self.api.delete_file(item["file_key"])
        except Exception:
            pass  # sync already succeeded; stale-object cleanup is best effort

    def _remember(self, record, identifiers):
        row = {
            "book_hash": record["hash"],
            "title": record["title"],
            "author": record["author"],
            "tags": record.get("tags"),
            "metadata": record["metadata"],
            "uploaded_at": ms_to_iso(record.get("uploadedAt")),
            "cover_hash": record.get("coverHash"),
            "metadata_updated_at": ms_to_iso(record.get("metadataUpdatedAt")),
        }
        self.by_hash[record["hash"]] = row
        for identifier in identifiers:
            self.by_identifier[identifier] = row
        self.blob_cache[record["hash"]] = True

    def upload(self, path):
        path = os.fspath(path)
        if os.path.splitext(path)[1].lower() != ".epub":
            raise ValueError("Only EPUB files are supported: %s" % path)
        if not os.path.isfile(path):
            raise ValueError("File does not exist: %s" % path)

        book, cover = extract_epub(path)
        source_hash = partial_md5(path)
        book["source_hash"] = source_hash
        cover_hash = partial_md5_bytes(cover) if cover else None
        now_ms = int(time.time() * 1000)
        wire = build_wire_book(book, source_hash, now_ms)
        identifiers = metadata_identifiers(wire["metadata"])
        candidates = []
        for identifier in identifiers:
            row = self.by_identifier.get(identifier)
            if row is not None and row not in candidates:
                candidates.append(row)
        server_row = pick_server_row(self.by_hash.get(source_hash), candidates)
        preserve_server_metadata(wire, server_row)
        plan = plan_push(server_row, wire, cover_hash, source_hash, self._blob_present)
        action = plan["action"]

        if action == "skip":
            return {"status": "skipped", "hash": server_row["book_hash"], "title": book["title"], "path": path}

        if action in ("new", "replace"):
            size = os.path.getsize(path)
            with open(path, "rb") as stream:
                self._upload(book_file_name(source_hash), stream, size, source_hash)
            if plan["upload_cover"] and cover:
                self._upload(cover_file_name(source_hash), io.BytesIO(cover), len(cover), source_hash)
            record = merge_for_push(
                wire,
                server_row,
                now_ms,
                uploaded_at_ms=now_ms,
                cover_hash=cover_hash if plan["upload_cover"] else None,
            )
            records = [record]
            replaced_hash = None
            if server_row is not None and server_row["book_hash"] != source_hash:
                replaced_hash = server_row["book_hash"]
                records.append(tombstone_record(server_row, now_ms))
            self.api.push_books(records)
            if replaced_hash:
                self._delete_files(replaced_hash)
            status = "uploaded" if action == "new" else "replaced"
        else:
            wire["hash"] = wire["bookHash"] = server_row["book_hash"]
            pushed_cover = plan["upload_cover"] and cover
            if pushed_cover:
                self._upload(
                    cover_file_name(server_row["book_hash"]),
                    io.BytesIO(cover),
                    len(cover),
                    server_row["book_hash"],
                )
            record = merge_for_push(
                wire,
                server_row,
                now_ms,
                cover_hash=cover_hash if pushed_cover else None,
            )
            self.api.push_books([record])
            status = "updated"

        self._remember(record, identifiers)
        return {"status": status, "hash": record["hash"], "title": book["title"], "path": path}
