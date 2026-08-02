import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import site_accounts


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="quota-tests-",
            ignore_cleanup_errors=True,
        )
        self.database = Path(self.temporary.name) / "site.sqlite3"
        self.patchers = [
            patch.object(site_accounts, "DB_PATH", self.database),
            patch.object(site_accounts, "DEFAULT_GENERATION_CREDITS", 10),
            patch.object(site_accounts, "DEFAULT_STORAGE_LIMIT_BYTES", 5 * 1024**3),
        ]
        for patcher in self.patchers:
            patcher.start()
        site_accounts.init_site_database()
        self.user = site_accounts.register_user("quota_user", "safe-password-123")

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    def test_success_consumes_one_credit_and_failure_refunds(self):
        initial = site_accounts.quota_snapshot(self.user["id"])
        self.assertEqual(initial["generation_balance"], 10)

        site_accounts.reserve_generation(self.user["id"], "failed-job")
        self.assertEqual(site_accounts.quota_snapshot(self.user["id"])["generation_balance"], 9)
        self.assertTrue(site_accounts.settle_generation_reservation("failed-job", False))
        refunded = site_accounts.quota_snapshot(self.user["id"])
        self.assertEqual(refunded["generation_balance"], 10)

        site_accounts.reserve_generation(self.user["id"], "successful-job")
        self.assertTrue(site_accounts.settle_generation_reservation("successful-job", True))
        consumed = site_accounts.quota_snapshot(self.user["id"])
        self.assertEqual(consumed["generation_balance"], 9)
        self.assertEqual(consumed["generation_consumed"], 1)
        self.assertEqual([entry["event_type"] for entry in consumed["ledger"][:4]], ["consume", "reserve", "refund", "reserve"])

    def test_storage_limit_blocks_new_generation_and_delete_releases_space(self):
        site_accounts.record_video_storage(
            "stored-job",
            self.user["id"],
            "https://media.test/preview.mp4",
            "https://media.test/original.mp4",
            5 * 1024**3,
        )
        full = site_accounts.quota_snapshot(self.user["id"])
        self.assertEqual(full["storage_available_bytes"], 0)
        self.assertFalse(full["can_generate"])
        with self.assertRaisesRegex(site_accounts.QuotaError, "storage_quota_exhausted"):
            site_accounts.reserve_generation(self.user["id"], "blocked-job")

        released = site_accounts.mark_video_storage_deleted("stored-job", self.user["id"])
        self.assertEqual(released, 5 * 1024**3)
        self.assertTrue(site_accounts.quota_snapshot(self.user["id"])["can_generate"])

    def test_admin_can_adjust_generation_and_storage_allowance(self):
        adjusted = site_accounts.adjust_user_quota(
            self.user["id"],
            generation_delta=5,
            storage_limit_bytes=8 * 1024**3,
        )
        self.assertEqual(adjusted["generation_balance"], 15)
        self.assertEqual(adjusted["storage_limit_bytes"], 8 * 1024**3)
        self.assertEqual(adjusted["ledger"][0]["event_type"], "adjust")


if __name__ == "__main__":
    unittest.main()
