import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app import auth, main


class AccountPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        auth._sessions.clear()
        auth.init(Path(self.temp_dir.name) / "accounts.json")
        auth._save_accounts([])
        for name in ("admin", "alice", "bob"):
            auth.add_account(name, "password123")
        self.tokens = {n: auth.create_session(n) for n in ("admin", "alice")}

    def tearDown(self):
        auth._sessions.clear()
        self.temp_dir.cleanup()

    async def test_diagnostics_admin_only(self):
        with self.assertRaises(HTTPException) as ctx:
            await main.get_diagnostics(pb_session=self.tokens["alice"])
        self.assertEqual(ctx.exception.status_code, 403)
        info = await main.get_diagnostics(pb_session=self.tokens["admin"])
        self.assertIn("history", info)

    async def test_user_cannot_change_others_password(self):
        req = main.ChangePasswordRequest(new_password="newpassword1")
        with self.assertRaises(HTTPException) as ctx:
            await main.change_password("bob", req, self.tokens["alice"])
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_user_can_change_own_password(self):
        req = main.ChangePasswordRequest(new_password="newpassword1")
        await main.change_password("alice", req, self.tokens["alice"])

    async def test_admin_can_change_anyone(self):
        req = main.ChangePasswordRequest(new_password="newpassword1")
        await main.change_password("bob", req, self.tokens["admin"])

    async def test_non_admin_cannot_delete(self):
        with self.assertRaises(HTTPException) as ctx:
            await main.delete_account("bob", self.tokens["alice"])
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_admin_cannot_be_deleted(self):
        with self.assertRaises(HTTPException) as ctx:
            await main.delete_account("admin", self.tokens["admin"])
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_admin_can_delete_others(self):
        await main.delete_account("bob", self.tokens["admin"])


if __name__ == "__main__":
    unittest.main()
