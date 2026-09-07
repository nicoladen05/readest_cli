import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from readest_cli import cli


class FakeLibrary:
    def __init__(self, api):
        pass

    def upload_books(self, paths):
        return [{"status": "uploaded", "hash": "abc", "title": "Book", "path": paths[0]}]


class CliTest(unittest.TestCase):
    def test_single_upload_json_is_the_only_stdout(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(cli, "make_client", return_value=object()), patch.object(
            cli, "ReadestLibrary", FakeLibrary
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main(["upload", "book.epub", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {
            "status": "uploaded",
            "hash": "abc",
            "title": "Book",
            "path": "book.epub",
        })
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
