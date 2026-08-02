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
            patch.object(site_accounts, "DEFAULT_POINTS_BALANCE", 10),
            patch.object(site_accounts, "DEFAULT_STORAGE_LIMIT_BYTES", 5 * 1024**3),
            patch.object(site_accounts, "DEFAULT_INVITER_REWARD_POINTS", 10),
            patch.object(site_accounts, "DEFAULT_INVITEE_REWARD_POINTS", 10),
            patch.object(site_accounts, "BILLING_MARKUP_MULTIPLIER", 2),
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

    def test_workflow_price_is_twice_the_configured_provider_cost(self):
        pricing = site_accounts.update_workflow_pricing(
            "OWN02",
            coze_cost_points=3,
            mihe_cost_points=2,
        )
        self.assertEqual(pricing["provider_cost_points"], 5)
        self.assertEqual(pricing["price_points"], 10)

        site_accounts.reserve_generation(self.user["id"], "priced-job", pricing["price_points"])
        self.assertEqual(site_accounts.quota_snapshot(self.user["id"])["points_balance"], 0)
        site_accounts.settle_generation_reservation("priced-job", False)
        self.assertEqual(site_accounts.quota_snapshot(self.user["id"])["points_balance"], 10)

    def test_approved_invitation_rewards_both_users_once(self):
        inviter_before = site_accounts.quota_snapshot(self.user["id"])
        invite_code = inviter_before["invite"]["code"]
        application = site_accounts.submit_registration_application(
            "invited@example.test",
            invite_code,
        )
        prepared, temporary_password = site_accounts.prepare_registration_approval(
            application["id"],
            self.user["id"],
        )
        self.assertEqual(prepared["invite_code"], invite_code)
        site_accounts.complete_registration_approval(application["id"])

        invitee = site_accounts.authenticate_user("invited@example.test", temporary_password)
        self.assertIsNotNone(invitee)
        inviter_after = site_accounts.quota_snapshot(self.user["id"])
        invitee_after = site_accounts.quota_snapshot(invitee["id"])
        self.assertEqual(inviter_after["points_balance"], 20)
        self.assertEqual(invitee_after["points_balance"], 20)
        self.assertEqual(inviter_after["invite"]["invited_count"], 1)
        self.assertEqual(inviter_after["ledger"][0]["event_type"], "invite_reward")
        self.assertEqual(invitee_after["ledger"][0]["event_type"], "welcome_bonus")

    def test_legacy_generation_balance_converts_to_points_only_once(self):
        site_accounts.quota_snapshot(self.user["id"])
        with site_accounts._connect() as db:
            db.execute(
                "UPDATE user_quotas SET generation_balance = 10 WHERE user_id = ?",
                (self.user["id"],),
            )
            db.execute("DELETE FROM schema_meta WHERE key = 'points_wallet_v1'")
            db.commit()
        with patch.object(site_accounts, "LEGACY_CREDIT_POINT_RATE", 4):
            site_accounts.init_site_database()
            self.assertEqual(site_accounts.quota_snapshot(self.user["id"])["points_balance"], 40)
            site_accounts.init_site_database()
            self.assertEqual(site_accounts.quota_snapshot(self.user["id"])["points_balance"], 40)

    def test_existing_user_receives_one_time_topup_to_new_1000_point_standard(self):
        site_accounts.quota_snapshot(self.user["id"])
        with site_accounts._connect() as db:
            db.execute(
                "UPDATE user_quotas SET generation_balance = 40 WHERE user_id = ?",
                (self.user["id"],),
            )
            db.execute("DELETE FROM schema_meta WHERE key = 'points_default_1000_v1'")
            db.commit()
        with (
            patch.object(site_accounts, "DEFAULT_POINTS_BALANCE", 1000),
            patch.object(site_accounts, "DEFAULT_GENERATION_CREDITS", 10),
            patch.object(site_accounts, "LEGACY_CREDIT_POINT_RATE", 4),
        ):
            site_accounts.init_site_database()
            topped_up = site_accounts.quota_snapshot(self.user["id"])
            self.assertEqual(topped_up["points_balance"], 1000)
            self.assertEqual(topped_up["ledger"][0]["units"], 960)
            site_accounts.init_site_database()
            self.assertEqual(site_accounts.quota_snapshot(self.user["id"])["points_balance"], 1000)


if __name__ == "__main__":
    unittest.main()
