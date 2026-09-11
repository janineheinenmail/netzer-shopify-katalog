#!/usr/bin/env python3
"""Vollstaendiger, ausschliesslich lesender Phase-1-Export.

Das kurzlebige Token wird nur als Konstruktorargument gehalten. Der Export
enthaelt weder Zugangsdaten noch Token und wird ausschliesslich unter dem von
Git ignorierten Verzeichnis ``private/`` gespeichert.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request


PRIVATE_DIR = Path("private")
EVIDENCE_PATH = PRIVATE_DIR / "setup-result.json"
EXPORT_PATH = PRIVATE_DIR / "shopify-phase-1-export.json"
INCOMPLETE_PATH = PRIVATE_DIR / "shopify-phase-1-incomplete.json"
MAX_PAGES = 100_000


class ExportError(RuntimeError):
    """Der Export ist fehlgeschlagen oder seine Vollstaendigkeit ist unklar."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def clear_previous_results() -> None:
    for path in (EVIDENCE_PATH, EXPORT_PATH, INCOMPLETE_PATH):
        path.unlink(missing_ok=True)
        if path.parent.exists():
            for temporary in path.parent.glob(f".{path.name}.*"):
                temporary.unlink(missing_ok=True)


class ShopifyGraphQL:
    def __init__(self, shop: str, api_version: str, token: str) -> None:
        self.url = f"https://{shop}/admin/api/{api_version}/graphql.json"
        self._token = token

    def execute(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        for attempt in range(6):
            request = urllib.request.Request(
                self.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": self._token,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 5:
                    try:
                        delay = float(exc.headers.get("Retry-After", "1"))
                    except (TypeError, ValueError):
                        delay = 1.0
                    delay = min(delay, 30.0)
                    time.sleep(max(delay, 0.1))
                    continue
                if exc.code in (401, 403):
                    raise ExportError(
                        f"Shopify-Berechtigungsfehler (HTTP {exc.code})"
                    ) from None
                raise ExportError(
                    f"Shopify antwortete mit HTTP-Status {exc.code}"
                ) from None
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise ExportError(
                    f"Shopify-Abruf fehlgeschlagen: {type(exc).__name__}"
                ) from None

            errors = payload.get("errors")
            if errors:
                codes = {
                    error.get("extensions", {}).get("code")
                    for error in errors
                    if isinstance(error, dict)
                    and isinstance(error.get("extensions"), dict)
                }
                if "THROTTLED" in codes and attempt < 5:
                    status = (
                        payload.get("extensions", {})
                        .get("cost", {})
                        .get("throttleStatus", {})
                    )
                    available = float(status.get("currentlyAvailable", 0))
                    restore = float(status.get("restoreRate", 1)) or 1
                    time.sleep(min(max((1 - available) / restore, 0.1), 30.0))
                    continue
                if codes & {"ACCESS_DENIED", "FORBIDDEN"}:
                    raise ExportError(
                        "Shopify GraphQL meldete einen Berechtigungsfehler"
                    )
                raise ExportError(
                    "Shopify GraphQL meldete einen Fehler; Details werden nicht protokolliert"
                )
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ExportError("Shopify lieferte keine verwertbaren Daten")
            return data
        raise ExportError("Shopify API-Limit blieb nach mehreren Warteversuchen aktiv")


def menu_item_fields(depth: int = 8) -> str:
    fields = (
        "id title type url resourceId tags resource { __typename ... on Node { id } }"
    )
    return (
        fields if depth == 0 else f"{fields} items {{ {menu_item_fields(depth - 1)} }}"
    )


MENUS_QUERY = """query ExportMenus($first:Int!,$after:String) {
  menus(first:$first,after:$after) {
    nodes { id handle title items { %s } }
    pageInfo { hasNextPage endCursor }
  }
}""" % menu_item_fields()

PRODUCTS_QUERY = """query ExportProducts($first:Int!,$after:String) {
  products(first:$first,after:$after,sortKey:ID) {
    nodes { id title handle descriptionHtml productType vendor status tags
      createdAt updatedAt publishedAt templateSuffix options { id name position values }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

PRODUCT_VARIANTS_QUERY = """query ExportProductVariants($id:ID!,$first:Int!,$after:String) {
  product(id:$id) { variants(first:$first,after:$after) {
    nodes { id title sku barcode price compareAtPrice inventoryQuantity inventoryPolicy
      taxable position selectedOptions { name value } image { id url altText }
    }
    pageInfo { hasNextPage endCursor }
  } }
}"""

PRODUCT_MEDIA_QUERY = """query ExportProductMedia($id:ID!,$first:Int!,$after:String) {
  product(id:$id) { media(first:$first,after:$after) {
    nodes { id alt mediaContentType status preview { image { id url altText width height } } }
    pageInfo { hasNextPage endCursor }
  } }
}"""

PRODUCT_COLLECTIONS_QUERY = """query ExportProductCollections($id:ID!,$first:Int!,$after:String) {
  product(id:$id) { collections(first:$first,after:$after) {
    nodes { id }
    pageInfo { hasNextPage endCursor }
  } }
}"""

COLLECTIONS_QUERY = """query ExportCollections($first:Int!,$after:String) {
  collections(first:$first,after:$after,sortKey:ID) {
    nodes { id title handle descriptionHtml updatedAt sortOrder templateSuffix
      ruleSet { appliedDisjunctively rules { column relation condition conditionObject { __typename } } }
      image { id url altText width height }
    }
    pageInfo { hasNextPage endCursor }
  }
}"""

COLLECTION_PRODUCTS_QUERY = """query ExportCollectionProducts($id:ID!,$first:Int!,$after:String) {
  collection(id:$id) { products(first:$first,after:$after,sortKey:ID) {
    nodes { id }
    pageInfo { hasNextPage endCursor }
  } }
}"""


def paginate(
    client: ShopifyGraphQL, query: str, root: str, parent_id: str | None = None
) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    cursor = None
    seen_cursors: set[str] = set()
    for _ in range(MAX_PAGES):
        variables: dict[str, object] = {"first": 100, "after": cursor}
        if parent_id is not None:
            variables["id"] = parent_id
        data = client.execute(query, variables)
        container = data.get(root) if parent_id is None else data.get(root)
        if parent_id is not None:
            if not isinstance(container, dict):
                raise ExportError(f"Shopify lieferte das Elternobjekt {root} nicht")
            connection_name = next(
                (
                    key
                    for key in ("variants", "media", "collections", "products")
                    if key in container
                ),
                None,
            )
            connection = container.get(connection_name) if connection_name else None
        else:
            connection = container
        if not isinstance(connection, dict) or not isinstance(
            connection.get("nodes"), list
        ):
            raise ExportError(f"Unvollstaendige Verbindung: {root}")
        nodes.extend(connection["nodes"])
        page_info = connection.get("pageInfo")
        if not isinstance(page_info, dict) or "hasNextPage" not in page_info:
            raise ExportError(f"Fehlende Seiteninformation: {root}")
        if not page_info["hasNextPage"]:
            return nodes
        next_cursor = page_info.get("endCursor")
        if (
            not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor in seen_cursors
        ):
            raise ExportError(f"Ungueltiger oder wiederholter Cursor: {root}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise ExportError(f"Sicherheitslimit fuer Seitennavigation erreicht: {root}")


def node_ids(nodes: list[dict[str, object]], kind: str) -> list[object]:
    if any(not isinstance(node.get("id"), str) or not node["id"] for node in nodes):
        raise ExportError(f"{kind} ohne ID empfangen")
    return [node["id"] for node in nodes]


def verify_memberships(
    products: list[dict[str, object]], collections: list[dict[str, object]]
) -> None:
    from_products = {
        (product["id"], collection_id)
        for product in products
        for collection_id in product["collectionIds"]
    }
    from_collections = {
        (product_id, collection["id"])
        for collection in collections
        for product_id in collection["productIds"]
    }
    if from_products != from_collections:
        raise ExportError(
            "Produktzugehoerigkeiten sind zwischen den Abrufen inkonsistent"
        )


def export_all(
    client: ShopifyGraphQL, identity: dict[str, object], api_version: str
) -> dict[str, object]:
    started_at = utc_now()
    menus = paginate(client, MENUS_QUERY, "menus")
    if sum(1 for menu in menus if menu.get("handle") == "main-menu-ii") != 1:
        raise ExportError("Menue main-menu-ii fehlt oder ist nicht eindeutig")
    products = paginate(client, PRODUCTS_QUERY, "products")
    for product in products:
        product_id = str(product.get("id", ""))
        if not product_id:
            raise ExportError("Produkt ohne ID empfangen")
        product["variants"] = paginate(
            client, PRODUCT_VARIANTS_QUERY, "product", product_id
        )
        product["media"] = paginate(client, PRODUCT_MEDIA_QUERY, "product", product_id)
        product["collectionIds"] = node_ids(
            paginate(client, PRODUCT_COLLECTIONS_QUERY, "product", product_id),
            "Kollektion",
        )
    collections = paginate(client, COLLECTIONS_QUERY, "collections")
    for collection in collections:
        collection_id = str(collection.get("id", ""))
        if not collection_id:
            raise ExportError("Kollektion ohne ID empfangen")
        collection["productIds"] = node_ids(
            paginate(client, COLLECTION_PRODUCTS_QUERY, "collection", collection_id),
            "Produkt",
        )
    verify_memberships(products, collections)
    return {
        "schemaVersion": 1,
        "complete": True,
        "startedAt": started_at,
        "completedAt": utc_now(),
        "apiVersion": api_version,
        "shopIdentity": identity,
        "counts": {
            "menus": len(menus),
            "products": len(products),
            "collections": len(collections),
        },
        "menus": menus,
        "products": products,
        "collections": collections,
    }
