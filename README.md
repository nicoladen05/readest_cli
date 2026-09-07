# readest-cli

A standalone, script-friendly CLI for uploading EPUB files to the Readest cloud library. It has no Calibre or Qt dependency and uses only the Python standard library at runtime.

> This is an independent CLI built from Readest's current Calibre plugin protocol. It is not an official Readest release.

## Install

Python 3.9 or newer is required.

```sh
python -m pip install .
# or, for an isolated command:
pipx install .
```

For development:

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Usage

```sh
readest login                         # Google in the browser
readest login --provider github       # google, apple, github, or discord
readest login --email you@example.com # password is read without echo
readest whoami
readest upload book.epub
readest upload *.epub
readest upload book.epub --json
readest list
readest list --json
readest logout
```

A single JSON upload prints one object. A batch prints an array, in input order:

```json
{"status":"uploaded","hash":"...","title":"The Example Book","path":"book.epub"}
```

Upload statuses are `uploaded`, `updated`, `replaced`, `skipped`, and `failed`. Diagnostics go to stderr. JSON mode writes only JSON to stdout.

Exit codes:

| Code | Meaning |
| ---: | --- |
| 0 | Success |
| 1 | API, file, or data error |
| 2 | Invalid command-line usage |
| 3 | Login or saved-session error |
| 4 | One or more files in a batch failed |
| 130 | Interrupted |

For self-hosted deployments, set `READEST_API_BASE` and `READEST_SUPABASE_URL`. The defaults are `https://web.readest.com/api` and `https://readest.supabase.co`.

## Programmatic use

Core operations do not print:

```python
from readest_cli import ReadestClient, ReadestLibrary
from readest_cli.config import load_tokens, save_tokens

api = ReadestClient(tokens=load_tokens(), on_tokens=save_tokens)
client = ReadestLibrary(api)
result = client.upload_book("book.epub")
books = client.list_books()
```

## Authentication flow

`readest login` follows `apps/readest-calibre-plugin/oauth.py`:

1. Bind an ephemeral localhost HTTP port.
2. Open Supabase `/auth/v1/authorize` with the selected provider and localhost redirect.
3. Serve a small landing page that forwards the URL fragment to `/callback` because fragments are not sent in HTTP requests.
4. Save the returned access token, refresh token, expiry, and lifetime.
5. Verify the session with Supabase `/auth/v1/user`.

Before API calls, the client refreshes through `/auth/v1/token?grant_type=refresh_token` when less than half the token lifetime remains (or less than 60 seconds remains). Users never copy access tokens.

The session is stored at `$XDG_CONFIG_HOME/readest/session.json`, or `~/.config/readest/session.json`. On POSIX systems the directory is mode `0700` and the atomically written file is mode `0600`. The password itself is never stored.

## EPUB and upload flow

Metadata extraction opens the EPUB as ZIP, reads `META-INF/container.xml`, resolves the OPF package, and extracts title, creators, languages, identifiers, publisher, date, description, and subjects. EPUB 2 `meta name="cover"`, EPUB 3 `cover-image`, and EPUB 2 guide/XHTML covers are supported.

The protocol follows the Readest Calibre plugin:

1. Compute Readest's sampled `partialMD5` for the EPUB and cover.
2. Pull book rows with paged `GET /api/sync?type=books&since=...&limit=1000`.
3. Match by content hash first, then by EPUB identifiers.
4. Confirm that an existing row still has a stored book object with `GET /api/storage/list?bookHash=...`.
5. Classify the operation as new, replacement, metadata/cover update, or unchanged.
6. Request each presigned URL with `POST /api/storage/upload`.
7. Upload bytes directly to the presigned URL with `PUT`.
8. Commit the merged row with `POST /api/sync`.
9. After a replacement is committed, tombstone the old row and best-effort delete its old objects.

Books use `Readest/Books/{hash}/{hash}.epub`; covers use `Readest/Books/{hash}/cover.png`. Updates carry forward server-side progress, reading status and its timestamp, group identity and timestamp, creation/upload timestamps, and existing cover fields. This is required because Readest's wire-to-database transformation can null omitted fields.

The EPUB is uploaded unchanged. Unlike the Calibre plugin, this CLI does not embed edited Calibre metadata into a temporary copy because there is no separate Calibre metadata source.

## Compatibility and assumptions

The implementation was checked against `readest/readest` commit `f819d39578e7cd54c1d6a752206c5aa5260d6838`.

- `api.py` and the browser callback are nearly unchanged adaptations of the standard-library-only plugin modules.
- `wire.py` adapts the plugin's wire construction, merge, duplicate planning, paths, and tombstones for EPUB metadata.
- `upload.py` is the non-Qt equivalent of the plugin worker.
- The public Supabase anonymous key is intentionally shipped by Readest clients. It is not a user credential.
- `/api/sync` does not expose a dedicated library-list route, so `readest list` performs a full books pull from epoch zero and filters tombstones.
- Identifier matching is case-insensitive. Exact content hash wins. If an EPUB has no identifier, changed-file versions cannot be linked safely and may become separate books.
- Cover bytes retain their source encoding even though the established cloud object name is `cover.png`; Readest decodes cover content rather than relying on the object suffix.
- Old cloud-object deletion is best effort and happens only after the replacement row is committed, so cleanup failure cannot lose the newly uploaded book.

## License and source

Readest and the adapted Calibre plugin code are AGPL-3.0. This project is therefore licensed under AGPL-3.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Adapted files retain Bilingify LLC's copyright notice and identify the modification.
