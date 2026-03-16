"""Unit tests for Matrix federation policy helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from mugen.core.utility.messaging_client_federation import (
    MessagingClientFederationPolicy,
    normalize_messaging_client_federation,
    parse_matrix_sender_domain,
    resolve_messaging_client_federation_policy,
)


class TestMessagingClientFederation(unittest.TestCase):
    """Covers normalization and runtime sender checks."""

    def test_normalize_and_resolve_policy(self) -> None:
        self.assertEqual(
            normalize_messaging_client_federation(
                {
                    "Allowed": [
                        " example.com ",
                        "example.com",
                        "example.com:8448",
                    ],
                    "Denied": [" blocked.example.com ", "blocked.example.com"],
                },
                field_name="Settings.federation",
            ),
            {
                "allowed": ["example.com", "example.com:8448"],
                "denied": ["blocked.example.com"],
            },
        )
        self.assertEqual(
            normalize_messaging_client_federation(
                {
                    "denied": ["blocked.example.com"],
                },
                field_name="Settings.federation",
                require_allowed=False,
            ),
            {
                "allowed": [],
                "denied": ["blocked.example.com"],
            },
        )
        self.assertEqual(
            resolve_messaging_client_federation_policy(
                SimpleNamespace(
                    allowed=["example.com"],
                    denied=["blocked.example.com"],
                ),
                field_name="matrix.federation",
            ),
            MessagingClientFederationPolicy(
                allowed=("example.com",),
                denied=("blocked.example.com",),
            ),
        )
        self.assertEqual(
            parse_matrix_sender_domain("@user:example.com:8448"),
            "example.com:8448",
        )

    def test_allow_checks_cover_allowed_and_denied_domains(self) -> None:
        policy = MessagingClientFederationPolicy(
            allowed=("example.com", "example.com:8448"),
            denied=("blocked.example.com",),
        )
        self.assertTrue(policy.allows_domain("example.com"))
        self.assertTrue(policy.allows_sender("@user:example.com:8448"))
        self.assertFalse(policy.allows_domain("blocked.example.com"))
        self.assertFalse(policy.allows_sender("@user:blocked.example.com"))
        self.assertFalse(policy.allows_sender(" "))
        self.assertFalse(policy.allows_sender(123))

    def test_invalid_policy_shapes_raise(self) -> None:
        cases = [
            (
                {},
                "Settings.federation.allowed must be a non-empty array of strings",
            ),
            (
                [],
                "Settings.federation must be a table",
            ),
            (
                {
                    "allowed": "example.com",
                },
                "Settings.federation.allowed must be an array of strings",
            ),
            (
                {
                    "allowed": ["", "example.com"],
                },
                "Settings.federation.allowed\\[0\\] must be a non-empty string",
            ),
            (
                {
                    "allowed": ["example.com"],
                    "denied": "blocked.example.com",
                },
                "Settings.federation.denied must be an array of strings",
            ),
            (
                {
                    "allowed": ["example.com"],
                    "extra": True,
                },
                "Settings.federation.extra is not supported",
            ),
            (
                {
                    " ": ["example.com"],
                },
                "Settings.federation key must be a non-empty string",
            ),
            (
                {
                    "Allowed": ["example.com"],
                    "allowed": ["blocked.example.com"],
                },
                "contains duplicate key 'allowed'",
            ),
            (
                {
                    "allowed": [123],
                },
                "Settings.federation.allowed\\[0\\] must be a non-empty string",
            ),
        ]

        for payload, message in cases:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(RuntimeError, message):
                    normalize_messaging_client_federation(
                        payload,
                        field_name="Settings.federation",
                    )


if __name__ == "__main__":
    unittest.main()
