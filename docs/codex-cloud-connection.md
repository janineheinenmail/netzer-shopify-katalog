# Verbindung der bestehenden Shopify-App in Codex Cloud

Stand: 11. September 2026

## Verbindungsmodell

Verwendet wird ausschliesslich die bereits installierte Dev-Dashboard-App
`Netzer Katalogbereinigung`. Ihre vorhandenen Scopes sind
`read_online_store_navigation`, `read_products` und `write_products`. Der
vorbereitete Ablauf nutzt trotz des vorhandenen Schreib-Scopes ausschliesslich
GraphQL-Queries. Er enthaelt keine Mutation und speichert kein Zugriffstoken.

Apps aus dem Shopify Dev Dashboard koennen fuer einen Shop, in dem sie
installiert sind, den Client-Credentials-Grant verwenden. Dabei werden Client ID
und Client Secret per `POST` an
`https://{shop}.myshopify.com/admin/oauth/access_token` gesendet. Shopify
beschreibt die resultierenden Tokens als kurzlebig (derzeit 24 Stunden); das
Setup erzeugt deshalb bei jedem Lauf ein neues Token und behaelt es nur im
Arbeitsspeicher. Quelle:
[Shopify: Client credentials grant](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens/client-credentials-grant).

## 1. Nicht geheime Umgebungsvariablen

Diese Werte in den **Environment variables** der Codex-Cloud-Umgebung setzen:

| Name | Wert |
| --- | --- |
| `SHOPIFY_SHOP_DOMAIN` | `netzer-dental.myshopify.com` |
| `SHOPIFY_EXPECTED_SHOP_DOMAIN` | `netzer-dental.myshopify.com` als unabhaengiger Sicherheitsvergleich |
| `SHOPIFY_EXPECTED_PRIMARY_DOMAIN` | `netzer-dental.de` |
| `SHOPIFY_API_VERSION` | Eine von der App unterstuetzte, stabile Version im Format `YYYY-MM` |

Die interne Domain darf nicht aus dem App-Namen, der Client ID oder der
oeffentlichen Domain geraten werden. Sie ist im Shopify-Admin beziehungsweise
im Dev Dashboard fuer die konkrete Installation zu bestaetigen. Zur Wahl und
Lebensdauer einer API-Version siehe
[Shopify: API versioning](https://shopify.dev/docs/api/usage/versioning).

## 2. Geschuetzte Secrets

Diese beiden Werte aus der bestehenden App in den **Secrets** der
Codex-Cloud-Umgebung hinterlegen:

| Secret | Inhalt |
| --- | --- |
| `SHOPIFY_CLIENT_ID` | Client ID von `Netzer Katalogbereinigung` |
| `SHOPIFY_CLIENT_SECRET` | Client Secret von `Netzer Katalogbereinigung` |

Die Werte nicht in Environment variables, Setup-Befehle, Chat, Repository oder
Logs kopieren. Codex-Cloud-Secrets stehen nach der offiziellen Dokumentation nur
waehrend des Setup-Skripts zur Verfuegung und werden vor der Agentenphase aus der
Umgebung entfernt. Das passt zu diesem Entwurf: Token-Erzeugung und
Identitaetsabfrage laufen vollstaendig im Setup; es wird kein Secret oder Token
in eine Datei zur spaeteren Nutzung uebertragen. Quelle:
[OpenAI: Codex cloud environments](https://developers.openai.com/codex/cloud/environments).

## 3. Setup-Skript und Netzwerkzugriff

Als Setup-Skript konfigurieren:

```bash
bash scripts/codex_cloud_setup.sh
```

Das Skript prueft zuerst, dass alle Variablen vorhanden sind. Das Python-Programm
validiert anschliessend lokal Ziel- und Erwartungsdomains gegen die fest
vorgegebenen Netzer-Dental-Domains, erzeugt ueber den Client-Credentials-Grant
ein Token im RAM und fuehrt zuerst genau die Query `ReadOnlyShopIdentity` aus.
Erst deren exakte Uebereinstimmung mit beiden erwarteten Domains erlaubt den
anschliessenden Nur-Lese-Export im selben Prozess.

Vor jedem Lauf werden ausschliesslich die bekannten alten Ergebnisdateien unter
`private/` entfernt. Nach erfolgreicher Identitaetspruefung enthaelt
`private/setup-result.json` Zeitstempel, beide tatsaechlich gelesenen Domains,
API-Version und Pruefstatus, aber keine Zugangsdaten und kein Token. Der Export
`private/shopify-phase-1-export.json` umfasst alle Menues samt verschachtelten
Eintraegen und Linkzielen, alle Produkte samt Varianten, Medien und
Kollektionszugehoerigkeiten sowie alle Kollektionen samt Regeln, Bildern und
vollstaendig paginierten Produktzugehoerigkeiten. Er enthaelt Start- und
Abschlusszeit, Objektzahlen und `complete: true`.

Jeder Setup-Versuch entfernt die bekannten alten Ergebnisdateien, bevor die
Konfiguration validiert wird. Auch eine fehlende Variable kann deshalb keinen
alten Erfolgsnachweis oder vollstaendigen Export zuruecklassen und erzeugt einen
aktuellen, nicht geheimen Fehlernachweis mit Zeitstempel und Fehlerart.

Bei Fehlern wird kein vollstaendiger Export hinterlassen. Stattdessen markiert
`private/shopify-phase-1-incomplete.json` den fehlgeschlagenen Stand mit
`complete: false`; er darf nicht ausgewertet werden. API-Drosselung wird mit
begrenzten Warteversuchen behandelt. Die Wartezeit wird aus angefragten Kosten,
verfuegbaren Punkten und Wiederherstellungsrate berechnet; fehlen diese Angaben,
kommt begrenztes exponentielles Backoff zum Einsatz. Nur Drosselungsantworten
werden wiederholt. Fehlende Berechtigungen, ungueltige oder wiederholte Cursor,
fehlende Seiteninformationen, uneindeutiges beziehungsweise fehlendes
`main-menu-ii` und dauerhaft aktive API-Limits brechen den Export ab.

Die Query-Texte sind durch Tests als reine Queries ohne Mutation abgesichert.
Eine Live-Validierung gegen das Schema der konfigurierten API-Version war bei
der Implementierung nicht moeglich: Die oeffentliche Shopify-Dokumentation war
aus der Ausfuehrungsumgebung nicht abrufbar, und ein Admin-Schema ist ohne die
nur im Setup verfuegbaren Zugangsdaten nicht erreichbar. Der naechste
Setup-Lauf sendet jede Query an genau den mit `SHOPIFY_API_VERSION`
konfigurierten Endpunkt. Schema- oder Feldfehler brechen den Lauf ab und lassen
keinen mit `complete: true` markierten Export zurueck. Diese Laufzeitpruefung
ersetzt keine vorab durchgefuehrte vollstaendige Schema-Validierung.

Der Setup-Schritt benoetigt ausgehenden HTTPS-Zugriff auf genau die bestaetigte
`*.myshopify.com`-Domain (TCP 443) fuer den Token-Endpunkt und die Shopify Admin
GraphQL API. Fuer die spaetere Agentenphase muss kein allgemeiner
Internetzugriff aktiviert werden. Falls der Katalogabruf ebenfalls sicher im
Setup ausgefuehrt wird, nutzt er dieselbe Domain. Die Codex-Dokumentation trennt
den Internetzugriff des Setup-Schritts von der standardmaessig abgeschalteten,
separat konfigurierbaren Internetfreigabe der Agentenphase. Quelle:
[OpenAI: Codex cloud internet access](https://developers.openai.com/codex/cloud/internet-access).

## Reihenfolge nach der Einrichtung

1. Setup ausfuehren; Identitaetscheck und Nur-Lese-Export laufen im selben
   Prozess.
2. Bei einer Abweichung nichts korrigieren oder umgehen, sondern die interne
   Shop-Domain beziehungsweise Installation im Shopify-Admin pruefen.
3. Nur wenn `private/shopify-phase-1-export.json` `complete: true` enthaelt, den
   gespeicherten Export in der Agentenphase auswerten. Zugriffstoken werden nie
   darin gespeichert.
4. Dann Menue `Main menu II` / `main-menu-ii`, Produkt- und
   Kollektionszahlen sowie Zuordnungen auswerten und den Phase-1-Pruefbericht
   erstellen.

Die offiziellen Seiten konnten aus dieser Ausfuehrungsumgebung am angegebenen
Stand wegen fehlender DNS-/Web-Erreichbarkeit nicht live geladen werden. Vor
der Eingabe der Secrets sollten die verlinkten Seiten im Browser geoeffnet und
insbesondere Token-Lebensdauer und Codex-Secret-Verfuegbarkeit auf eventuelle
Aenderungen geprueft werden.



## Optimierter Export nach Setup-Timeout

Ein beobachteter Setup-Lauf wurde nach 1200 Sekunden von der Umgebung beendet.
Der Export liest nun zehn Produkte pro Seite mit den ersten fuenf Varianten,
Medien und Kollektionen je Produkt. Kollektionen werden zu zehn pro Seite mit
je zehn Produkt-IDs gelesen. Jede noch offene Unterverbindung wird ab ihrem
bereits gelieferten Cursor vollstaendig nachgeladen. Es gehen keine bisherigen
Exportfelder verloren. Der Vergleich der Mitgliedschaften aus beiden Richtungen
bleibt aktiv; Duplikate und fehlende Seiteninformationen brechen den Export ab.

Der Setup-Prozess verwendet ungepufferte Python-Ausgabe. Zeitstempel, Seiten- und
Objektzahlen sowie API-Wartezeiten erscheinen sofort im Prozessprotokoll; die
Oberflaeche kann deren Anzeige weiterhin verzoegern. Keine Produktnamen, IDs,
Zugangsdaten oder Antwortinhalte werden in diese Fortschrittsmeldungen aufgenommen.

Ein internes Zeitbudget von 1080 Sekunden ab Python-Start begrenzt weitere
Exportanfragen und Warteversuche, um vor dem beobachteten Plattformlimit einen
Fehlermarker schreiben zu koennen. Dies ist keine Laufzeitgarantie: Plattformstart,
Netzwerk und Dateisystem liegen teilweise ausserhalb dieser Kontrolle. Bei einem
harten Plattformabbruch kann ein Fehlermarker weiterhin fehlen. Nur ein aktueller
vollstaendiger Export darf ausgewertet werden.

Nach Merge: Caching ausgeschaltet lassen, unveraendert
`bash scripts/codex_cloud_setup.sh` verwenden und eine neue Aufgabe auf `main`
starten. Keine Secrets in der Agentenphase verwenden. Die Optimierung wurde mit
simulierten Seiten und Shopify-Schemavalidierung geprueft; eine gemessene Laufzeit
fuer den echten Katalog liegt noch nicht vor.
