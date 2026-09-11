#!/usr/bin/env bash
# Codex-Cloud-Setup: Token im RAM, Identitaetspruefung und lesender Export.
set -euo pipefail

# Keine Debug-Ausgabe (`set -x`), keine Argumente und keine Token-Datei: Secrets
# werden nur an den Kindprozess vererbt und das kurzlebige Token bleibt in dessen RAM.
# Der Python-Prozess entfernt vor jeder Konfigurationspruefung alte Ergebnisse,
# damit auch ein unvollstaendig konfigurierter neuer Versuch keinen alten Erfolg
# zuruecklassen kann.
exec python3 scripts/run_shopify_setup.py
