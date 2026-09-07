# Copyright (C) 2026 readest-cli contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""Small, dependency-free EPUB metadata and cover extractor."""

import posixpath
import re
import urllib.parse
import zipfile
from xml.etree import ElementTree as ET

MAX_XML_SIZE = 10 * 1024 * 1024
MAX_COVER_SIZE = 25 * 1024 * 1024


class EpubError(ValueError):
    pass


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _safe_member(base, href):
    href = urllib.parse.unquote((href or "").split("#", 1)[0])
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), href))
    if not path or path == "." or path.startswith("../") or path.startswith("/"):
        raise EpubError("EPUB contains an unsafe path")
    return path


def _read_limited(archive, name, limit):
    try:
        info = archive.getinfo(name)
    except KeyError as error:
        raise EpubError("EPUB is missing %s" % name) from error
    if info.file_size > limit:
        raise EpubError("EPUB member is too large: %s" % name)
    return archive.read(info)


def _xml(archive, name):
    try:
        return ET.fromstring(_read_limited(archive, name, MAX_XML_SIZE))
    except ET.ParseError as error:
        raise EpubError("Invalid XML in %s: %s" % (name, error)) from error


def _text(element):
    return "".join(element.itertext()).strip() if element is not None else ""


def _all_text(parent, name):
    return [_text(element) for element in parent.iter() if _local_name(element.tag) == name and _text(element)]


def _identifier(element):
    value = _text(element)
    scheme = next(
        (v for k, v in element.attrib.items() if _local_name(k).lower() == "scheme"), ""
    )
    if scheme and ":" not in value:
        return "%s:%s" % (scheme.lower(), value)
    return value


def _isbn(identifiers):
    for identifier in identifiers:
        compact = re.sub(r"[^0-9Xx]", "", identifier.rsplit(":", 1)[-1])
        if len(compact) in (10, 13):
            return compact
    return None


def _cover_path(archive, opf_path, package):
    manifest = next((e for e in package.iter() if _local_name(e.tag) == "manifest"), None)
    if manifest is None:
        return None
    items = {item.get("id"): item for item in manifest if _local_name(item.tag) == "item"}

    cover_id = None
    for element in package.iter():
        if _local_name(element.tag) == "meta" and element.get("name", "").lower() == "cover":
            cover_id = element.get("content")
            break
    item = items.get(cover_id)
    if item is None:
        item = next(
            (entry for entry in items.values() if "cover-image" in entry.get("properties", "").split()),
            None,
        )
    if item is None:
        reference = next(
            (
                e
                for e in package.iter()
                if _local_name(e.tag) == "reference" and "cover" in e.get("type", "").lower()
            ),
            None,
        )
        if reference is not None:
            path = _safe_member(opf_path, reference.get("href"))
            media_type = ""
        else:
            return None
    else:
        path = _safe_member(opf_path, item.get("href"))
        media_type = item.get("media-type", "")

    if media_type.startswith("image/") or path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return path

    # EPUB 2 guide entries often point to an XHTML cover page.
    try:
        page = _xml(archive, path)
        image = next(
            (e for e in page.iter() if _local_name(e.tag) in ("img", "image") and (e.get("src") or e.get("href"))),
            None,
        )
        return _safe_member(path, image.get("src") or image.get("href")) if image is not None else None
    except EpubError:
        return None


def extract_epub(path):
    """Return ``(metadata_dict, cover_bytes_or_none)`` for an EPUB path."""
    try:
        with zipfile.ZipFile(path) as archive:
            container = _xml(archive, "META-INF/container.xml")
            rootfile = next(
                (e for e in container.iter() if _local_name(e.tag) == "rootfile" and e.get("full-path")),
                None,
            )
            if rootfile is None:
                raise EpubError("EPUB container has no package document")
            opf_path = _safe_member("", rootfile.get("full-path"))
            package = _xml(archive, opf_path)
            metadata = next((e for e in package if _local_name(e.tag) == "metadata"), None)
            if metadata is None:
                raise EpubError("EPUB package has no metadata")

            title = next(iter(_all_text(metadata, "title")), "")
            if not title:
                raise EpubError("EPUB has no title")
            identifiers = [
                _identifier(element)
                for element in metadata.iter()
                if _local_name(element.tag) == "identifier" and _text(element)
            ]
            book = {
                "title": title,
                "authors": _all_text(metadata, "creator"),
                "languages": _all_text(metadata, "language"),
                "identifiers": identifiers,
                "isbn": _isbn(identifiers),
                "publisher": next(iter(_all_text(metadata, "publisher")), None),
                "pubdate": next(iter(_all_text(metadata, "date")), None),
                "comments": next(iter(_all_text(metadata, "description")), None),
                "tags": _all_text(metadata, "subject"),
            }
            cover_path = _cover_path(archive, opf_path, package)
            cover = _read_limited(archive, cover_path, MAX_COVER_SIZE) if cover_path else None
            return book, cover
    except (OSError, zipfile.BadZipFile) as error:
        raise EpubError("Not a valid EPUB: %s" % error) from error
