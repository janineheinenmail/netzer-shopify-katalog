import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "run_shopify_setup.py"
SPEC = importlib.util.spec_from_file_location("run_shopify_setup", MODULE_PATH)
setup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(setup)


class RunShopifySetupTests(unittest.TestCase):
    def test_export_timeout_records_incomplete_without_success_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(setup.exporter, "EVIDENCE_PATH", root / "evidence.json"),
                patch.object(setup.exporter, "EXPORT_PATH", root / "export.json"),
                patch.object(setup.exporter, "INCOMPLETE_PATH", root / "incomplete.json"),
                patch.object(setup.probe, "validate_configuration", return_value=("netzer-dental.myshopify.com", "netzer-dental.myshopify.com", "netzer-dental.de", "2026-07", "id", "secret")),
                patch.object(setup.probe, "exchange_token", return_value="token"),
                patch.object(setup.probe, "fetch_identity", return_value={"myshopifyDomain": "netzer-dental.myshopify.com", "primaryDomain": {"host": "netzer-dental.de"}}),
                patch.object(setup.exporter, "export_all", side_effect=setup.exporter.ExportError("Export-Zeitbudget erreicht")),
            ):
                self.assertEqual(setup.main(), 2)
            self.assertFalse((root / "export.json").exists())
            self.assertIn('"complete":false', (root / "incomplete.json").read_text())

    def test_missing_configuration_removes_old_export_and_records_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "setup-result.json"
            export = root / "shopify-phase-1-export.json"
            incomplete = root / "shopify-phase-1-incomplete.json"
            evidence.write_text('{"status":"identity_verified"}')
            export.write_text('{"complete":true}')

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(setup.exporter, "EVIDENCE_PATH", evidence),
                patch.object(setup.exporter, "EXPORT_PATH", export),
                patch.object(setup.exporter, "INCOMPLETE_PATH", incomplete),
            ):
                self.assertEqual(setup.main(), 2)

            self.assertFalse(evidence.exists())
            self.assertFalse(export.exists())
            self.assertTrue(incomplete.exists())
            self.assertIn('"complete":false', incomplete.read_text())
            self.assertIn('"status":"configuration_failed"', incomplete.read_text())
            self.assertIn("SHOPIFY_SHOP_DOMAIN", incomplete.read_text())


if __name__ == "__main__":
    unittest.main()

