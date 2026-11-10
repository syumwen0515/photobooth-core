import json
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import auth


class InitialAdminPasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.accounts_file = Path(self.temp_dir.name) / "accounts.json"
        auth._sessions.clear()
        auth._failed_logins.clear()

    def tearDown(self):
        auth._sessions.clear()
        auth._failed_logins.clear()
        self.temp_dir.cleanup()

    def test_new_install_does_not_use_predictable_password(self):
        with self.assertLogs("app.auth", level="WARNING") as captured:
            auth.init(self.accounts_file)

        self.assertFalse(auth.verify_credentials("admin", "admin"))
        generated_password = captured.output[0].rsplit("：", 1)[-1]
        self.assertGreaterEqual(len(generated_password), 20)
        self.assertTrue(auth.verify_credentials("admin", generated_password))

    def test_existing_admin_admin_account_is_rotated(self):
        salt = secrets.token_hex(16)
        self.accounts_file.write_text(
            json.dumps([{
                "username": "admin",
                "password_hash": auth._hash_password_pbkdf2("admin", salt),
                "salt": salt,
                "algo": "pbkdf2",
            }]),
            encoding="utf-8",
        )

        replacement = "replacement-password-2026"
        with patch.object(auth, "INITIAL_ADMIN_PASSWORD", replacement):
            auth.init(self.accounts_file)

        self.assertFalse(auth.verify_credentials("admin", "admin"))
        self.assertTrue(auth.verify_credentials("admin", replacement))

    def test_password_change_revokes_all_user_sessions(self):
        with patch.object(auth, "INITIAL_ADMIN_PASSWORD", "test-initial-admin-password"):
            auth.init(self.accounts_file)
        auth.add_account("staff", "old-password-123")
        sessions = [auth.create_session("staff") for _ in range(2)]

        ok, _ = auth.change_password("staff", "new-password-123")

        self.assertTrue(ok)
        self.assertTrue(all(auth.validate_session(token) is None for token in sessions))

    def test_account_deletion_revokes_all_user_sessions(self):
        with patch.object(auth, "INITIAL_ADMIN_PASSWORD", "test-initial-admin-password"):
            auth.init(self.accounts_file)
        auth.add_account("staff", "old-password-123")
        sessions = [auth.create_session("staff") for _ in range(2)]

        ok, _ = auth.delete_account("staff")

        self.assertTrue(ok)
        self.assertTrue(all(auth.validate_session(token) is None for token in sessions))


if __name__ == "__main__":
    unittest.main()