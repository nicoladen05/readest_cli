import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from readest_cli.config import load_tokens, save_tokens, session_path


class ConfigTest(unittest.TestCase):
    def test_session_round_trip_uses_private_permissions(self):
        tokens = {"access_token": "a", "refresh_token": "r"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": directory}
        ):
            save_tokens(tokens)
            self.assertEqual(load_tokens(), tokens)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(session_path().stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(session_path().parent.stat().st_mode), 0o700)
            save_tokens(None)
            self.assertFalse(session_path().exists())


if __name__ == "__main__":
    unittest.main()
