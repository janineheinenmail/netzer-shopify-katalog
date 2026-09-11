#!/usr/bin/env python3
"""Minimaler, strikt lesender Shopify-Identitaetscheck fuer Codex Cloud.

Das Skript tauscht die Client-Zugangsdaten der bestehenden Dev-Dashboard-App
gegen ein kurzlebiges Admin-API-Token und sendet damit genau eine GraphQL-Query
auf Shop-Metadaten. Katalogdaten werden nicht abgerufen. Geheimnisse und Token
werden weder ausgegeben noch persistiert.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request


DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
VERSION_RE = re.compile(r"^\d{4}-\d{2}$")
QUERY = """query ReadOnlyShopIdentity {
  shop {
    name
    myshopifyDomain
    primaryDomain { host }
  }
}"""


class ConfigurationError(RuntimeError):
    """Eine sichere, erforderliche Konfiguration fehlt oder ist ungueltig."""


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"Erforderliche Umgebungsvariable fehlt: {name}")
    return value


def validate_configuration() -> tuple[str, str, str, str, str, str]:
    shop = required("SHOPIFY_SHOP_DOMAIN").lower()
    expected_shop = required("SHOPIFY_EXPECTED_SHOP_DOMAIN").lower()
    expected_primary = required("SHOPIFY_EXPECTED_PRIMARY_DOMAIN").lower()
    api_version = required("SHOPIFY_API_VERSION")
    client_id = required("SHOPIFY_CLIENT_ID")
    client_secret = required("SHOPIFY_CLIENT_SECRET")

    if not DOMAIN_RE.fullmatch(shop) or not DOMAIN_RE.fullmatch(expected_shop):
        raise ConfigurationError("Shop-Domains muessen gueltige *.myshopify.com-Domains sein")
    if shop != expected_shop:
        raise ConfigurationError("Ziel- und erwartete Shop-Domain stimmen nicht ueberein")
    if expected_primary != "netzer-dental.de" and not expected_primary.endswith(
        ".netzer-dental.de"
    ):
        raise ConfigurationError("Erwartete Primaerdomain gehoert nicht zu netzer-dental.de")
    if not VERSION_RE.fullmatch(api_version):
        raise ConfigurationError("SHOPIFY_API_VERSION muss das Format YYYY-MM haben")
    return shop, expected_shop, expected_primary, api_version, client_id, client_secret


def exchange_token(shop: str, client_id: str, client_secret: str) -> str:
    """Client-Credentials-Grant; das Ergebnis bleibt ausschliesslich im RAM."""
    url = f"https://{shop}/admin/oauth/access_token"
    request = urllib.request.Request(
        url,
        data=json.dumps(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Token-Endpunkt antwortete mit HTTP-Status {exc.code}") from None
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Token-Endpunkt lieferte kein verwertbares Zugriffstoken")
    return token


def fetch_identity(shop: str, api_version: str, token: str) -> dict[str, object]:
    url = f"https://{shop}/admin/api/{api_version}/graphql.json"
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": QUERY}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # Keine Response-Bodies ausgeben: Sie koennten unvorhergesehene Daten enthalten.
        raise RuntimeError(f"Shopify antwortete mit HTTP-Status {exc.code}") from None
    if payload.get("errors"):
        raise RuntimeError("Shopify GraphQL meldete einen Fehler; Details werden nicht protokolliert")
    try:
        return payload["data"]["shop"]
    except (KeyError, TypeError):
        raise RuntimeError("Shopify lieferte keine verwertbare Shop-Identitaet") from None


def verify_identity(identity: dict[str, object], expected_shop: str, expected_primary: str) -> None:
    actual_shop = str(identity.get("myshopifyDomain", "")).lower()
    primary = identity.get("primaryDomain")
    actual_primary = str(primary.get("host", "")).lower() if isinstance(primary, dict) else ""
    if actual_shop != expected_shop or actual_primary != expected_primary:
        raise RuntimeError("IDENTITAET NICHT BESTAETIGT; Katalogabruf ist gesperrt")


def main() -> int:
    try:
        shop, expected_shop, expected_primary, version, client_id, client_secret = (
            validate_configuration()
        )
        token = exchange_token(shop, client_id, client_secret)
        identity = fetch_identity(shop, version, token)
        verify_identity(identity, expected_shop, expected_primary)
    except (ConfigurationError, RuntimeError) as exc:
        print(f"ABBRUCH: {exc}", file=sys.stderr)
        return 2
    print("OK: Netzer-Dental-Shopidentitaet wurde bestaetigt; keine Katalogdaten gelesen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
