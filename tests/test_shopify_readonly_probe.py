import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "shopify_readonly_probe.py"
SPEC = importlib.util.spec_from_file_location("shopify_readonly_probe", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


class ReadOnlyProbeTests(unittest.TestCase):
    def test_configuration_rejects_different_target(self):
        values = {
            "SHOPIFY_SHOP_DOMAIN": "wrong-shop.myshopify.com",
            "SHOPIFY_EXPECTED_SHOP_DOMAIN": "netzer.myshopify.com",
            "SHOPIFY_EXPECTED_PRIMARY_DOMAIN": "netzer-dental.de",
            "SHOPIFY_API_VERSION": "2026-07",
            "SHOPIFY_CLIENT_ID": "not-a-real-client-id",
            "SHOPIFY_CLIENT_SECRET": "not-a-real-client-secret",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(probe.ConfigurationError):
                probe.validate_configuration()

    def test_configuration_rejects_foreign_primary_domain(self):
        values = {
            "SHOPIFY_SHOP_DOMAIN": "netzer.myshopify.com",
            "SHOPIFY_EXPECTED_SHOP_DOMAIN": "netzer.myshopify.com",
            "SHOPIFY_EXPECTED_PRIMARY_DOMAIN": "example.org",
            "SHOPIFY_API_VERSION": "2026-07",
            "SHOPIFY_CLIENT_ID": "not-a-real-client-id",
            "SHOPIFY_CLIENT_SECRET": "not-a-real-client-secret",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaises(probe.ConfigurationError):
                probe.validate_configuration()

    def test_identity_rejects_mismatch(self):
        identity = {
            "myshopifyDomain": "another-shop.myshopify.com",
            "primaryDomain": {"host": "netzer-dental.de"},
        }
        with self.assertRaises(RuntimeError):
            probe.verify_identity(
                identity, "netzer.myshopify.com", "netzer-dental.de"
            )

    def test_identity_accepts_exact_domains(self):
        identity = {
            "myshopifyDomain": "netzer.myshopify.com",
            "primaryDomain": {"host": "netzer-dental.de"},
        }
        probe.verify_identity(identity, "netzer.myshopify.com", "netzer-dental.de")

    @patch.object(probe.urllib.request, "urlopen")
    def test_token_exchange_uses_client_credentials_without_logging(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"access_token":"short-lived-token"}'
        response.__iter__.return_value = iter(response.read.return_value.splitlines())

        token = probe.exchange_token(
            "netzer.myshopify.com", "client-id", "client-secret"
        )

        self.assertEqual(token, "short-lived-token")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://netzer.myshopify.com/admin/oauth/access_token")
        self.assertIn(b'"grant_type": "client_credentials"', request.data)


if __name__ == "__main__":
    unittest.main()
