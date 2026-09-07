import hashlib
import io
import json
import time
import unittest

from readest_cli.api import ReadestClient, meta_hash, partial_md5_bytes


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        data = request.data.read() if hasattr(request.data, "read") else request.data
        self.requests.append((request.get_method(), request.full_url, request.headers, data))
        status, body = self.responses.pop(0)
        return status, body if isinstance(body, bytes) else json.dumps(body).encode()


class HashTest(unittest.TestCase):
    def test_small_file_is_full_md5(self):
        self.assertEqual(partial_md5_bytes(b"hello"), hashlib.md5(b"hello").hexdigest())

    def test_metadata_hash_prefers_uuid(self):
        expected = hashlib.md5(b"Title|Alice|abc").hexdigest()
        self.assertEqual(meta_hash("Title", ["Alice"], ["isbn:123", "urn:uuid:abc"]), expected)


class ApiTest(unittest.TestCase):
    def test_refreshes_then_pulls_books(self):
        transport = FakeTransport(
            [
                (200, {"access_token": "new", "refresh_token": "next", "expires_at": 9999999999, "expires_in": 3600}),
                (200, {"books": [{"book_hash": "h"}]}),
            ]
        )
        saved = []
        client = ReadestClient(
            api_base="https://api.example/api",
            supabase_url="https://supabase.example",
            anon_key="anon",
            tokens={"access_token": "old", "refresh_token": "refresh", "expires_at": int(time.time()), "expires_in": 3600},
            on_tokens=saved.append,
            transport=transport,
        )
        self.assertEqual(client.pull_books(), [{"book_hash": "h"}])
        self.assertIn("grant_type=refresh_token", transport.requests[0][1])
        self.assertEqual(transport.requests[1][1], "https://api.example/api/sync?type=books&since=0&limit=1000")
        self.assertEqual(saved[-1]["access_token"], "new")

    def test_presigned_put_has_raw_body_and_length(self):
        transport = FakeTransport([(204, b"")])
        client = ReadestClient(transport=transport)
        client.put_file("https://storage.example/book", io.BytesIO(b"epub"), 4)
        method, _, headers, body = transport.requests[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(headers["Content-length"], "4")
        self.assertEqual(body, b"epub")


if __name__ == "__main__":
    unittest.main()
