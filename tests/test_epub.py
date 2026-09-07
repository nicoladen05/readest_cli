import tempfile
import unittest
import zipfile
from pathlib import Path

from readest_cli.epub import EpubError, extract_epub

CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Example &amp; Test</dc:title>
    <dc:creator>Alice</dc:creator><dc:creator>Bob</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier>urn:uuid:12345678-1234-1234-1234-123456789abc</dc:identifier>
    <dc:identifier>isbn:9781234567897</dc:identifier>
    <dc:publisher>Example Press</dc:publisher><dc:date>2024-01-02</dc:date>
    <dc:description>A description.</dc:description>
    <dc:subject>Fiction</dc:subject><dc:subject>Testing</dc:subject>
  </metadata>
  <manifest><item id="cover" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/></manifest>
</package>"""


def make_epub(path, opf=OPF):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OPS/content.opf", opf)
        archive.writestr("OPS/images/cover.jpg", b"jpeg-cover")


class EpubTest(unittest.TestCase):
    def test_extracts_metadata_and_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            make_epub(path)
            book, cover = extract_epub(path)

        self.assertEqual(book["title"], "Example & Test")
        self.assertEqual(book["authors"], ["Alice", "Bob"])
        self.assertEqual(book["languages"], ["en"])
        self.assertEqual(book["publisher"], "Example Press")
        self.assertEqual(book["pubdate"], "2024-01-02")
        self.assertEqual(book["comments"], "A description.")
        self.assertEqual(book["tags"], ["Fiction", "Testing"])
        self.assertEqual(book["isbn"], "9781234567897")
        self.assertEqual(cover, b"jpeg-cover")

    def test_rejects_missing_title(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            make_epub(path, OPF.replace("<dc:title>Example &amp; Test</dc:title>", ""))
            with self.assertRaises(EpubError):
                extract_epub(path)


if __name__ == "__main__":
    unittest.main()
