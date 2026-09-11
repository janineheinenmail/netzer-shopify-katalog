# Netzer-Dental Shopify-Katalog

Werkzeuge und Dokumentation fuer die kontrollierte Katalogpruefung. Phase 1 ist
strikt lesend. Der aktuelle Einrichtungsstand und die benoetigten sicheren
Zugangsschritte stehen in [`docs/phase-1-status.md`](docs/phase-1-status.md).

Die bestehende, bereits installierte Dev-Dashboard-App
`Netzer Katalogbereinigung` wird verwendet; es wird keine zweite App angelegt. Die
Einrichtung erfolgt als Codex-Cloud-Umgebung, nicht ueber eine lokale `.env`:

```bash
bash scripts/codex_cloud_setup.sh
```

Die nicht geheimen Variablen und die beiden geschuetzten Secrets sind in
[`docs/codex-cloud-connection.md`](docs/codex-cloud-connection.md) beschrieben.
Der Setup-Schritt tauscht Client-Zugangsdaten im Arbeitsspeicher gegen ein
kurzlebiges Token, prueft zuerst die Shop-Identitaet und exportiert danach
ausschliesslich lesend Menues, Produkte und Kollektionen nach `private/`. Die
Agentenphase verwendet nur diesen Export. `.env`, Exporte, Sicherungen und Logs
werden durch `.gitignore` ausgeschlossen.
