#!/usr/bin/env bash
# Codex-Cloud-Setup: nur Token-Erzeugung im RAM und Shop-Identitaetspruefung.
set -euo pipefail

required_variables=(
  SHOPIFY_SHOP_DOMAIN
  SHOPIFY_EXPECTED_SHOP_DOMAIN
  SHOPIFY_EXPECTED_PRIMARY_DOMAIN
  SHOPIFY_API_VERSION
  SHOPIFY_CLIENT_ID
  SHOPIFY_CLIENT_SECRET
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    printf 'ABBRUCH: Erforderliche Cloud-Variable fehlt: %s\n' "$variable" >&2
    exit 2
  fi
done

# Keine Debug-Ausgabe (`set -x`), keine Argumente und keine Token-Datei: Secrets
# werden nur an den Kindprozess vererbt und das kurzlebige Token bleibt in dessen RAM.
exec python3 scripts/shopify_readonly_probe.py
