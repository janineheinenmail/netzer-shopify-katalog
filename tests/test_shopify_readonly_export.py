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

    def test_nested_page_continues_at_embedded_cursor(self):
        initial = {"nodes": [{"id": "c1"}], "pageInfo": {"hasNextPage": True, "endCursor": "c1cursor"}}
        client = MagicMock()
        client.execute.return_value = {"product": {"collections": {
            "nodes": [{"id": "c2"}], "pageInfo": {"hasNextPage": False, "endCursor": "c2cursor"}
        }}}
        result = exporter.finish_nested(client, {"id": "p1", "collections": initial}, "collections", exporter.PRODUCT_COLLECTIONS_QUERY, "product")
        self.assertEqual([n["id"] for n in result], ["c1", "c2"])
        self.assertEqual(client.execute.call_args.args[1]["after"], "c1cursor")
        client.execute.assert_called_once()

    def test_nested_duplicate_and_invalid_page_info_rejected(self):
        for page_info, next_nodes in [
            ({"hasNextPage": "false"}, []),
            ({"hasNextPage": True, "endCursor": "a"}, [{"id": "c1"}]),
        ]:
            with self.subTest(page_info=page_info):
                client = MagicMock()
                client.execute.return_value = {"product": {"collections": {
                    "nodes": next_nodes, "pageInfo": {"hasNextPage": False}
                }}}
                with self.assertRaises(exporter.ExportError):
                    exporter.finish_nested(client, {"id": "p1", "collections": {"nodes": [{"id": "c1"}], "pageInfo": page_info}}, "collections", exporter.PRODUCT_COLLECTIONS_QUERY, "product")

    def test_export_reuses_embedded_pages_and_preserves_output(self):
        def connection(nodes):
            return {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}
        client = MagicMock()
        products = [{"id": f"p{i}", "title": "private-title", "variants": connection([{"id": f"v{i}"}]), "media": connection([]), "collections": connection([{"id": "c1"}])} for i in range(10)]
        client.execute.side_effect = [
            {"menus": connection([{"id": "m1", "handle": "main-menu-ii"}])},
            {"products": connection(products)},
            {"collections": connection([{"id": "c1", "products": connection([{"id": f"p{i}"} for i in range(10)])}])},
        ]
        with patch("builtins.print") as output:
            result = exporter.export_all(client, {}, "2026-07")
        self.assertTrue(result["complete"])
        self.assertEqual(result["counts"], {"menus": 1, "products": 10, "collections": 1})
        self.assertEqual(result["products"][0]["variants"], [{"id": "v0"}])
        self.assertEqual(result["products"][0]["collectionIds"], ["c1"])
        self.assertNotIn("collections", result["products"][0])
        self.assertEqual(client.execute.call_count, 3)
        self.assertNotIn("private-title", str(output.call_args_list))
        self.assertTrue(all(call.kwargs.get("flush") for call in output.call_args_list))

    @patch.object(exporter.urllib.request, "urlopen")
    def test_deadline_stops_before_network_request(self, urlopen):
        client = exporter.ShopifyGraphQL("netzer-dental.myshopify.com", "2026-07", "token", deadline=0)
        with self.assertRaisesRegex(exporter.ExportError, "Zeitbudget"):
            client.execute("query { shop { id } }", {})
        urlopen.assert_not_called()

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

