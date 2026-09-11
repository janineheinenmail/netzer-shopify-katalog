#!/usr/bin/env python3
"""Fuehrt Identitaetspruefung und Export atomar in derselben Setup-Phase aus."""

from __future__ import annotations

import sys
import time

import shopify_readonly_export as exporter
import shopify_readonly_probe as probe


def main() -> int:
    deadline = time.monotonic() + exporter.EXPORT_BUDGET_SECONDS
    exporter.progress("Setup gestartet; Zeitbudget 1080 Sekunden")
    exporter.clear_previous_results()
    try:
        shop, expected_shop, expected_primary, version, client_id, client_secret = (
            probe.validate_configuration()
        )
        token = probe.exchange_token(shop, client_id, client_secret)
        identity = probe.fetch_identity(shop, version, token)
        probe.verify_identity(identity, expected_shop, expected_primary)
        evidence = {
            "checkedAt": exporter.utc_now(),
            "status": "identity_verified",
            "apiVersion": version,
            "myshopifyDomain": str(identity.get("myshopifyDomain", "")).lower(),
            "primaryDomain": str(
                identity.get("primaryDomain", {}).get("host", "")
            ).lower()
            if isinstance(identity.get("primaryDomain"), dict)
            else None,
        }
        exporter.atomic_json(exporter.EVIDENCE_PATH, evidence)
        print(
            "OK: Netzer-Dental-Shopidentitaet wurde bestaetigt; keine Katalogdaten vor der Pruefung gelesen."
        )
        client = exporter.ShopifyGraphQL(shop, version, token, deadline=deadline)
        result = exporter.export_all(client, identity, version)
        exporter.atomic_json(exporter.EXPORT_PATH, result)
        print(
            "OK: Vollstaendiger Nur-Lese-Export gespeichert "
            f"(Menues: {result['counts']['menus']}, Produkte: {result['counts']['products']}, "
            f"Kollektionen: {result['counts']['collections']})."
        )
        return 0
    except (probe.ConfigurationError, RuntimeError, OSError) as exc:
        exporter.EXPORT_PATH.unlink(missing_ok=True)
        status = (
            "configuration_failed"
            if isinstance(exc, probe.ConfigurationError)
            else "export_failed"
        )
        exporter.atomic_json(
            exporter.INCOMPLETE_PATH,
            {
                "complete": False,
                "failedAt": exporter.utc_now(),
                "status": status,
                "error": str(exc),
            },
        )
        print(f"ABBRUCH: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

