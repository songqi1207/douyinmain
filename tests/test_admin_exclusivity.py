import gc
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import site_accounts


class AdminExclusivityTests(unittest.TestCase):
    def test_only_configured_admin_email_keeps_admin_role(self):
        with tempfile.TemporaryDirectory(prefix="admin-exclusivity-") as temporary:
            database = Path(temporary) / "site.sqlite3"
            with (
                patch.object(site_accounts, "DB_PATH", database),
                patch.dict(
                    site_accounts.os.environ,
                    {
                        "SITE_ADMIN_EMAIL": "owner@example.test",
                        "SITE_ADMIN_PASSWORD": "owner-password-123",
                    },
                ),
            ):
                site_accounts.init_site_database()
                db = sqlite3.connect(database)
                try:
                    db.execute(
                        """INSERT INTO users
                           (id, username, email, password_hash, password_salt, role, active,
                            must_change_password, created_at)
                           VALUES ('rogue', 'rogue', 'rogue@example.test', 'hash', '00',
                                   'admin', 1, 0, 1)"""
                    )
                    db.commit()
                finally:
                    db.close()

                site_accounts.ensure_configured_admin()

                db = sqlite3.connect(database)
                try:
                    roles = dict(db.execute("SELECT email, role FROM users").fetchall())
                finally:
                    db.close()
                self.assertEqual(roles["owner@example.test"], "admin")
                self.assertEqual(roles["rogue@example.test"], "user")
                gc.collect()


if __name__ == "__main__":
    unittest.main()
