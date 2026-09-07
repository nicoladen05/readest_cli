import tempfile
import unittest
import zipfile
from pathlib import Path

from readest_cli.upload import ReadestLibrary
from readest_cli.wire import merge_for_push, preserve_server_metadata

CONTAINER = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>'
OPF = '''<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Agent Book</dc:title><dc:creator>A. Writer</dc:creator><dc:identifier>urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</dc:identifier></metadata><manifest><item id="c" href="cover.png" media-type="image/png" properties="cover-image"/></manifest></package>'''


def make_epub(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("book.opf", OPF)
        archive.writestr("cover.png", b"png")


class FakeAPI:
    def __init__(self):
        self.upload_names = []
        self.puts = []
        self.pushes = []
        self.book_hash = None

    def pull_books(self):
        return []

    def list_files(self, book_hash):
        return [{"file_key": "user/Readest/Books/%s/%s.epub" % (book_hash, book_hash)}]

    def get_upload_url(self, name, size, book_hash):
        self.upload_names.append((name, size, book_hash))
        self.book_hash = book_hash
        return {"uploadUrl": "https://storage.example/" + str(len(self.upload_names))}

    def put_file(self, url, stream, size):
        self.puts.append((url, stream.read(), size))

    def push_books(self, records):
        self.pushes.append(records)
        return {"books": records}

    def delete_file(self, key):
        raise AssertionError("new upload must not delete")


class UploadTest(unittest.TestCase):
    def test_mock_upload_and_same_batch_duplicate_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.epub"
            make_epub(path)
            api = FakeAPI()
            results = ReadestLibrary(api).upload_books([path, path])

        self.assertEqual([item["status"] for item in results], ["uploaded", "skipped"])
        self.assertEqual(len(api.upload_names), 2)  # EPUB and cover, once each
        self.assertTrue(api.upload_names[0][0].endswith(".epub"))
        self.assertTrue(api.upload_names[1][0].endswith("cover.png"))
        self.assertEqual(len(api.pushes), 1)
        record = api.pushes[0][0]
        self.assertEqual(record["hash"], api.book_hash)
        self.assertEqual(record["title"], "Agent Book")
        self.assertEqual(record["uploadedAt"], record["updatedAt"])

    def test_unknown_server_metadata_is_not_erased(self):
        wire = {"metadata": {"title": "Local", "author": "A"}}
        row = {"metadata": '{"title":"Remote","author":"B","series":"Keep Me"}'}
        preserve_server_metadata(wire, row)
        self.assertEqual(
            wire["metadata"],
            {"title": "Local", "author": "A", "series": "Keep Me"},
        )

    def test_merge_preserves_server_reading_and_group_fields(self):
        wire = {
            "hash": "a" * 32,
            "bookHash": "a" * 32,
            "title": "T",
            "author": "A",
            "tags": [],
            "metadata": {"title": "T", "author": "A"},
            "createdAt": 1,
        }
        row = {
            "book_hash": "a" * 32,
            "title": "T",
            "author": "A",
            "tags": [],
            "metadata": '{"title":"T","author":"A"}',
            "created_at": "2024-01-01T00:00:00Z",
            "uploaded_at": "2024-01-02T00:00:00Z",
            "group_id": "g",
            "group_name": "Shelf",
            "group_updated_at": "2024-01-03T00:00:00Z",
            "progress": [3, 10],
            "reading_status": "reading",
            "reading_status_updated_at": "2024-01-04T00:00:00Z",
        }
        record = merge_for_push(wire, row, 2)
        self.assertEqual(record["groupId"], "g")
        self.assertEqual(record["groupName"], "Shelf")
        self.assertEqual(record["groupUpdatedAt"], 1704240000000)
        self.assertEqual(record["progress"], [3, 10])
        self.assertEqual(record["readingStatus"], "reading")
        self.assertEqual(record["readingStatusUpdatedAt"], 1704326400000)


if __name__ == "__main__":
    unittest.main()
