# Copyright (C) 2026 readest-cli contributors
# SPDX-License-Identifier: AGPL-3.0-only

"""Local session storage, restricted to the current OS user."""

import json
import os
import tempfile
from pathlib import Path

APP_DIR = "readest"
SESSION_FILE = "session.json"


class ConfigError(ValueError):
    pass


def config_dir():
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root).expanduser() / APP_DIR if root else Path.home() / ".config" / APP_DIR


def session_path():
    return config_dir() / SESSION_FILE


def load_tokens():
    path = session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ConfigError("Cannot read saved Readest session: %s" % error) from error
    if not isinstance(data, dict) or not data.get("refresh_token"):
        raise ConfigError("Saved Readest session is invalid; run 'readest logout'")
    return data


def save_tokens(tokens):
    directory = config_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    path = session_path()
    if tokens is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    fd, temporary = tempfile.mkstemp(prefix=".session-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(tokens, stream)
            stream.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
