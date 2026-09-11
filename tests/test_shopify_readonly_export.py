import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "shopify_readonly_export.py"
SPEC = importlib.util.spec_from_file_location("shopify_readonly_export", MODULE_PATH)
exporter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(exporter)


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def execute(self, query, variables):
        return next(self.responses)


class ReadOnlyExportTests(unittest.TestCase):
    @patch.object(exporter.time, "sleep")
    @patch.object(exporter.urllib.request, "urlopen")
    def test_throttled_query_waits_for_requested_cost(self, urlopen, sleep):
        throttled = MagicMock()
        throttled.__enter__.return_value.read.return_value = json.dumps(
            {
                "errors": [{"extensions": {"code": "THROTTLED"}}],
                "extensions": {
                    "cost": {
                        "requestedQueryCost": 50,
                        "throttleStatus": {
                            "currentlyAvailable": 10,
                            "restoreRate": 20,
                        },
                    }
                },
            }
        ).encode()
        successful = MagicMock()
        successful.__enter__.return_value.read.return_value = (
            b'{"data":{"shop":{"id":"1"}}}'
        )
        urlopen.side_effect = [throttled, successful]

        client = exporter.ShopifyGraphQL(
            "netzer-dental.myshopify.com", "2026-07", "short-lived-token"
        )
        self.assertEqual(
            client.execute("query { shop { id } }", {}), {"shop": {"id": "1"}}
        )

        sleep.assert_called_once_with(2.0)

    def test_export_queries_are_read_only(self):
        queries = (
            exporter.MENUS_QUERY,
            exporter.PRODUCTS_QUERY,
            exporter.PRODUCT_VARIANTS_QUERY,
            exporter.PRODUCT_MEDIA_QUERY,
            exporter.PRODUCT_COLLECTIONS_QUERY,
            exporter.COLLECTIONS_QUERY,
            exporter.COLLECTION_PRODUCTS_QUERY,
        )
        self.assertTrue(all("mutation" not in query.lower() for query in queries))

    def test_paginate_reads_every_page(self):
        client = FakeClient(
            [
                {
                    "products": {
                        "nodes": [{"id": "1"}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "a"},
                    }
                },
                {
                    "products": {
                        "nodes": [{"id": "2"}],
                        "pageInfo": {"hasNextPage": False, "endCursor": "b"},
                    }
                },
            ]
        )
        self.assertEqual(
            [item["id"] for item in exporter.paginate(client, "query", "products")],
            ["1", "2"],
        )

    def test_paginate_rejects_repeated_cursor(self):
        client = FakeClient(
            [
                {
                    "products": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": True, "endCursor": "a"},
                    }
                },
                {
                    "products": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": True, "endCursor": "a"},
                    }
                },
            ]
        )
        with self.assertRaises(exporter.ExportError):
            exporter.paginate(client, "query", "products")

    def test_atomic_json_does_not_store_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            exporter.atomic_json(path, {"complete": True, "apiVersion": "2026-07"})
            self.assertEqual(
                json.loads(path.read_text()),
                {"complete": True, "apiVersion": "2026-07"},
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_clear_previous_results_removes_all_known_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [
                Path(directory) / name for name in ("evidence", "export", "incomplete")
            ]
            for path in paths:
                path.write_text("old")
            with (
                patch.object(exporter, "EVIDENCE_PATH", paths[0]),
                patch.object(exporter, "EXPORT_PATH", paths[1]),
                patch.object(exporter, "INCOMPLETE_PATH", paths[2]),
            ):
                exporter.clear_previous_results()
            self.assertTrue(all(not path.exists() for path in paths))

    def test_verify_memberships_rejects_inconsistent_snapshot(self):
        products = [{"id": "p1", "collectionIds": ["c1"]}]
        collections = [{"id": "c1", "productIds": []}]
        with self.assertRaises(exporter.ExportError):
            exporter.verify_memberships(products, collections)


if __name__ == "__main__":
    unittest.main()
