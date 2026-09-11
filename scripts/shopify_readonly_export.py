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
EXPORT_BUDGET_SECONDS = 1080


def progress(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)


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
    def __init__(self, shop: str, api_version: str, token: str, deadline: float | None = None) -> None:
        self.url = f"https://{shop}/admin/api/{api_version}/graphql.json"
        self._token = token
        self.deadline = deadline if deadline is not None else time.monotonic() + EXPORT_BUDGET_SECONDS
        self.requests = 0

    def check_deadline(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ExportError("Export-Zeitbudget erreicht; kein vollstaendiger Export")
        return remaining

    def wait_for_retry(self, delay: float) -> None:
        if delay >= self.check_deadline():
            raise ExportError("Export-Zeitbudget waehrend API-Drosselung erreicht")
        progress(f"API-Drosselung: Wartezeit {delay:.1f} Sekunden")
        time.sleep(delay)

    def execute(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        body = json.dumps({"query": query, "variables": variables}).encode()
        for attempt in range(6):
            remaining = self.check_deadline()
            self.requests += 1
            if self.requests == 1 or self.requests % 25 == 0:
                progress(f"API-Anfragen gestartet: {self.requests}")
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
                with urllib.request.urlopen(request, timeout=min(60, remaining)) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 5:
                    try:
                        delay = float(exc.headers.get("Retry-After", "1"))
                    except (TypeError, ValueError):
                        delay = 2**attempt
                    delay = min(delay, 30.0)
                    self.wait_for_retry(max(delay, 0.1))
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
                    self.wait_for_retry(self._throttle_delay(payload, attempt))
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

    @staticmethod
    def _throttle_delay(payload: object, attempt: int) -> float:
        """Wartezeit fuer eine abgewiesene Query, begrenzt auf 0,1 bis 30 s."""
        try:
            cost = payload["extensions"]["cost"]
            requested = float(cost["requestedQueryCost"])
            status = cost["throttleStatus"]
            available = float(status["currentlyAvailable"])
            restore = float(status["restoreRate"])
            if requested < 0 or available < 0 or restore <= 0:
                raise ValueError
            return min(max((requested - available) / restore, 0.1), 30.0)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return min(float(2**attempt), 30.0)


def menu_item_fields(depth: int = 8) -> str:
    fields = "id title type url resourceId tags"
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
      variants(first:5) {
    nodes { id title sku barcode price compareAtPrice inventoryQuantity inventoryPolicy
      taxable position selectedOptions { name value } image { id url altText }
    }
    pageInfo { hasNextPage endCursor }
}
      media(first:5) {
    nodes { id alt mediaContentType status preview { image { id url altText width height } } }
    pageInfo { hasNextPage endCursor }
}
      collections(first:5) {
    nodes { id }
    pageInfo { hasNextPage endCursor }
}
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
      products(first:10,sortKey:ID) {  nodes { id } pageInfo { hasNextPage endCursor }  }
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
    client: ShopifyGraphQL, query: str, root: str, parent_id: str | None = None,
    *, first: int = 100, initial_connection: dict | None = None,
    connection_name: str | None = None,
) -> list[dict[str, object]]:
    nodes: list[dict[str, object]] = []
    cursor = None
    seen_cursors: set[str] = set()
    seen_ids: set[str] = set()
    for page in range(MAX_PAGES):
        if page == 0 and initial_connection is not None:
            connection = initial_connection
        else:
            variables: dict[str, object] = {"first": first, "after": cursor}
            if parent_id is not None:
                variables["id"] = parent_id
            data = client.execute(query, variables)
            container = data.get(root)
            if parent_id is not None:
                if not isinstance(container, dict):
                    raise ExportError(f"Shopify lieferte das Elternobjekt {root} nicht")
                key = connection_name or next(
                    (key for key in ("variants", "media", "collections", "products") if key in container), None
                )
                connection = container.get(key)
            else:
                connection = container
        if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
            raise ExportError(f"Unvollstaendige Verbindung: {root}")
        for node in connection["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
                raise ExportError(f"Objekt ohne ID: {root}")
            if node["id"] in seen_ids:
                raise ExportError(f"Doppelte ID waehrend Pagination: {root}")
            seen_ids.add(node["id"])
            nodes.append(node)
        page_info = connection.get("pageInfo")
        if not isinstance(page_info, dict) or type(page_info.get("hasNextPage")) is not bool:
            raise ExportError(f"Fehlende Seiteninformation: {root}")
        if parent_id is None:
            progress(f"{root}: Seite {page + 1}, bisher {len(nodes)} Objekte gelesen")
        if not page_info["hasNextPage"]:
            return nodes
        next_cursor = page_info.get("endCursor")
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors or not connection["nodes"]:
            raise ExportError(f"Ungueltiger oder wiederholter Cursor: {root}")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise ExportError(f"Sicherheitslimit fuer Seitennavigation erreicht: {root}")


def finish_nested(client, parent, field, query, root):
    initial = parent.get(field)
    if not isinstance(initial, dict):
        raise ExportError(f"Fehlende eingebettete Verbindung: {field}")
    return paginate(client, query, root, parent["id"], initial_connection=initial, connection_name=field)


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
    products = paginate(client, PRODUCTS_QUERY, "products", first=10)
    progress(f"Produktbasis gelesen: {len(products)}; vervollstaendige Unterverbindungen")
    for index, product in enumerate(products, 1):
        product["variants"] = finish_nested(client, product, "variants", PRODUCT_VARIANTS_QUERY, "product")
        product["media"] = finish_nested(client, product, "media", PRODUCT_MEDIA_QUERY, "product")
        product["collectionIds"] = node_ids(finish_nested(client, product, "collections", PRODUCT_COLLECTIONS_QUERY, "product"), "Kollektion")
        del product["collections"]
        if index % 25 == 0 or index == len(products):
            progress(f"Produkte mit vollstaendigen Unterverbindungen: {index}/{len(products)}")
    collections = paginate(client, COLLECTIONS_QUERY, "collections", first=10)
    for index, collection in enumerate(collections, 1):
        collection["productIds"] = node_ids(finish_nested(client, collection, "products", COLLECTION_PRODUCTS_QUERY, "collection"), "Produkt")
        del collection["products"]
        if index % 25 == 0 or index == len(collections):
            progress(f"Kollektionen mit vollstaendigen Mitgliedschaften: {index}/{len(collections)}")
    progress("Pruefe gegenseitige Produkt-Kollektionszuordnungen")
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

