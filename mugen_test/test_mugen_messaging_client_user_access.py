"""Unit tests for messaging client user-access policy helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from mugen.core.utility.messaging_client_user_access import (
    MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL,
    MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT,
    MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
    MessagingClientUserAccessPolicy,
    normalize_messaging_client_user_access,
    resolve_messaging_client_user_access_policy,
)


class TestMessagingClientUserAccess(unittest.TestCase):
    """Covers normalization and runtime sender checks."""

    def test_normalize_and_resolve_policies(self) -> None:
        self.assertEqual(
            normalize_messaging_client_user_access(
                {
                    "Mode": "allow_only",
                    "Users": [" @a:example.com ", "@a:example.com", "@b:example.com"],
                },
                field_name="Settings.user_access",
            ),
            {
                "mode": MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
                "users": ["@a:example.com", "@b:example.com"],
            },
        )
        self.assertEqual(
            resolve_messaging_client_user_access_policy(
                {
                    "mode": "allow-all-except",
                    "users": ["15550001"],
                    "denied_message": "Not enabled",
                },
                field_name="whatsapp.user_access",
                allow_denied_message=True,
            ),
            MessagingClientUserAccessPolicy(
                mode=MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT,
                users=("15550001",),
                denied_message="Not enabled",
            ),
        )
        self.assertEqual(
            resolve_messaging_client_user_access_policy(
                SimpleNamespace(
                    mode="allow_only",
                    users=["@allowed:example.com"],
                    denied_message=None,
                ),
                field_name="matrix.user_access",
            ),
            MessagingClientUserAccessPolicy(
                mode=MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
                users=("@allowed:example.com",),
            ),
        )
        self.assertEqual(
            resolve_messaging_client_user_access_policy(None),
            MessagingClientUserAccessPolicy(
                mode=MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL,
            ),
        )

    def test_allow_checks_cover_all_modes(self) -> None:
        allow_all = MessagingClientUserAccessPolicy()
        self.assertTrue(allow_all.allows("@u:example.com"))

        allow_all_except = MessagingClientUserAccessPolicy(
            mode=MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ALL_EXCEPT,
            users=("15550001",),
        )
        self.assertFalse(allow_all_except.allows("15550001"))
        self.assertTrue(allow_all_except.allows("15550002"))

        allow_only = MessagingClientUserAccessPolicy(
            mode=MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
            users=("@allowed:example.com",),
        )
        self.assertTrue(allow_only.allows("@allowed:example.com"))
        self.assertFalse(allow_only.allows("@blocked:example.com"))
        self.assertFalse(allow_only.allows(" "))
        self.assertFalse(allow_only.allows(123))

    def test_invalid_policy_shapes_raise(self) -> None:
        cases = [
            (
                {"mode": "allow-all", "users": ["@u:example.com"]},
                "Settings.user_access.users must be empty when mode=allow-all",
                True,
            ),
            (
                {"mode": "allow-only", "users": []},
                "mode=allow-only",
                True,
            ),
            (
                {"mode": "allow-all", "users": [], "denied_message": "Nope"},
                "denied_message is only supported",
                True,
            ),
            (
                {"mode": "unsupported", "users": []},
                "must be one of",
                True,
            ),
            (
                [],
                "Settings.user_access must be a table",
                True,
            ),
            (
                {"mode": "allow-only", "users": "bad"},
                "Settings.user_access.users must be an array of strings",
                True,
            ),
            (
                {"mode": "allow-only", "users": ["", "@u:example.com"]},
                "Settings.user_access.users\\[0\\] must be a non-empty string",
                True,
            ),
            (
                {
                    "Mode": "allow-only",
                    "mode": "allow-all",
                    "users": ["@u:example.com"],
                },
                "contains duplicate key 'mode'",
                True,
            ),
            (
                {"mode": "allow-only", "users": ["@u:example.com"], "extra": True},
                "Settings.user_access.extra is not supported",
                True,
            ),
            (
                {
                    "mode": "allow-only",
                    "users": ["@u:example.com"],
                    "denied_message": "Nope",
                },
                "Settings.user_access.denied_message is not supported",
                False,
            ),
            (
                {"mode": "", "users": []},
                "Settings.user_access.mode must be a non-empty string",
                True,
            ),
        ]

        for payload, message, allow_denied_message in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RuntimeError, message):
                    normalize_messaging_client_user_access(
                        payload,
                        field_name="Settings.user_access",
                        allow_denied_message=allow_denied_message,
                    )


if __name__ == "__main__":
    unittest.main()
