import os
import unittest
from unittest.mock import patch

from utils.email_delivery import send_registration_application_received


class EmailDeliveryTests(unittest.TestCase):
    def test_registration_application_email_targets_configured_admin_inbox(self):
        captured = []
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.example.test",
                "SMTP_FROM": "sender@example.test",
                "REGISTRATION_NOTIFICATION_EMAIL": "admin@example.test",
            },
            clear=False,
        ), patch("utils.email_delivery._send_message", side_effect=captured.append):
            send_registration_application_received(
                "applicant@example.test",
                "https://example.test/business/admin/registrations",
            )

        self.assertEqual(len(captured), 1)
        message = captured[0]
        self.assertEqual(message["To"], "admin@example.test")
        self.assertEqual(message["From"], "sender@example.test")
        self.assertIn("applicant@example.test", message.get_content())
        self.assertIn("/business/admin/registrations", message.get_content())


if __name__ == "__main__":
    unittest.main()
