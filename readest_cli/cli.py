# Copyright (C) 2026 readest-cli contributors
# SPDX-License-Identifier: AGPL-3.0-only

import argparse
import getpass
import json
import os
import sys
import webbrowser

from .api import (
    DEFAULT_API_BASE,
    DEFAULT_SUPABASE_URL,
    AuthRequiredError,
    ReadestAPIError,
    ReadestClient,
)
from .auth import PROVIDERS, OAuthCallbackServer, build_authorize_url
from .config import ConfigError, load_tokens, save_tokens
from .epub import EpubError
from .upload import ReadestLibrary

EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_PARTIAL = 4


def make_client(tokens=None):
    return ReadestClient(
        api_base=os.environ.get("READEST_API_BASE", DEFAULT_API_BASE),
        supabase_url=os.environ.get("READEST_SUPABASE_URL", DEFAULT_SUPABASE_URL),
        tokens=load_tokens() if tokens is None else tokens,
        on_tokens=save_tokens,
    )


def _json(value):
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def login(args):
    client = make_client(tokens={})
    if args.email:
        password = getpass.getpass("Readest password: ")
        user = client.sign_in_password(args.email, password)
    else:
        server = OAuthCallbackServer()
        port = server.start()
        try:
            url = build_authorize_url(client.supabase_url, args.provider, port)
            if not args.json:
                print("Opening browser for Readest login...")
            if not webbrowser.open(url):
                print("Open this URL in a browser: %s" % url, file=sys.stderr)
            result = server.wait(args.timeout)
        finally:
            server.stop()
        if not result:
            raise AuthRequiredError("Login timed out")
        if result.get("error"):
            raise AuthRequiredError(result.get("error_description") or result["error"])
        if not result.get("access_token") or not result.get("refresh_token"):
            raise AuthRequiredError("Login callback did not contain a session")
        client.set_session(result)
        user = client.get_user()
    if args.json:
        _json({"status": "logged_in", "email": user.get("email")})
    else:
        print("Logged in%s." % ((" as " + user["email"]) if user.get("email") else ""))
    return 0


def logout(args):
    try:
        try:
            client = make_client()
        except ConfigError:
            client = None
        if client:
            client.sign_out()
    finally:
        save_tokens(None)
    if args.json:
        _json({"status": "logged_out"})
    else:
        print("Logged out.")
    return 0


def whoami(args):
    user = make_client().get_user()
    if args.json:
        _json(user)
    else:
        print(user.get("email") or user.get("id") or "Logged in")
    return 0


def list_books(args):
    books = ReadestLibrary(make_client()).list_books()
    if args.json:
        _json(books)
    else:
        for row in sorted(books, key=lambda item: (item.get("title") or "").casefold()):
            author = row.get("author") or ""
            print("%s\t%s\t%s" % (row.get("book_hash", ""), row.get("title", ""), author))
    return 0


def upload(args):
    results = ReadestLibrary(make_client()).upload_books(args.paths)
    failed = [result for result in results if result["status"] == "failed"]
    for result in failed:
        print("%s: %s" % (result["path"], result.get("error", "Upload failed")), file=sys.stderr)
    if args.json:
        _json(results[0] if len(results) == 1 else results)
    elif len(results) == 1:
        result = results[0]
        if result["status"] != "failed":
            print(result["path"])
            print("Title: %s" % result["title"])
            print({
                "uploaded": "Uploaded to Readest",
                "replaced": "Replaced in Readest",
                "updated": "Updated in Readest",
                "skipped": "Already up to date",
            }[result["status"]])
    else:
        labels = {
            "uploaded": "uploaded",
            "replaced": "replaced",
            "updated": "updated",
            "skipped": "already up to date",
            "failed": "failed",
        }
        for status in labels:
            count = sum(result["status"] == status for result in results)
            if count:
                print("%d %s" % (count, labels[status]))
    return EXIT_PARTIAL if failed else 0


def parser():
    root = argparse.ArgumentParser(prog="readest", description="Upload EPUB books to Readest")
    commands = root.add_subparsers(dest="command", required=True)

    login_parser = commands.add_parser("login", help="log in with browser OAuth")
    login_parser.add_argument("--provider", choices=PROVIDERS, default="google")
    login_parser.add_argument("--email", help="use email/password instead of browser OAuth")
    login_parser.add_argument("--timeout", type=int, default=300, help="OAuth timeout in seconds")
    login_parser.add_argument("--json", action="store_true")
    login_parser.set_defaults(run=login)

    logout_parser = commands.add_parser("logout", help="remove the saved session")
    logout_parser.add_argument("--json", action="store_true")
    logout_parser.set_defaults(run=logout)

    whoami_parser = commands.add_parser("whoami", help="show the current account")
    whoami_parser.add_argument("--json", action="store_true")
    whoami_parser.set_defaults(run=whoami)

    upload_parser = commands.add_parser("upload", help="upload one or more EPUB files")
    upload_parser.add_argument("paths", nargs="+")
    upload_parser.add_argument("--json", action="store_true")
    upload_parser.set_defaults(run=upload)

    list_parser = commands.add_parser("list", help="list cloud library books")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(run=list_books)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except (AuthRequiredError, ConfigError) as error:
        print("readest: %s" % error, file=sys.stderr)
        return EXIT_AUTH
    except (ReadestAPIError, EpubError, OSError, ValueError) as error:
        print("readest: %s" % error, file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("readest: canceled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
