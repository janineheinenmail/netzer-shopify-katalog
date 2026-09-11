# Phase 1: Status und sichere Zugangsvoraussetzungen

Stand: 11. September 2026

## Ergebnis der Repository- und Zugangspruefung

Die App `Netzer Katalogbereinigung` wurde bereits ueber das Shopify Dev Dashboard
erstellt und im Netzer-Dental-Shop mit `read_online_store_navigation`,
`read_products` und `write_products` installiert. Es wird keine zweite App
angelegt. Die vorhandene Schreibberechtigung wird in diesem Auftrag nicht
verwendet: Die vorbereiteten Skripte enthalten keine Mutation und keinen
Schreib-Endpunkt.

Die tatsaechliche interne `*.myshopify.com`-Adresse ist noch nicht bestaetigt.
Deshalb wurden **keine** Shopify-Anfragen und **keine** Schreiboperationen
ausgefuehrt. Insbesondere konnte noch nicht festgestellt werden, ob das Menue
`Main menu II` mit dem Handle `main-menu-ii` existiert.

Folglich liegen derzeit keine tatsaechlich gelesenen Produkt- oder
Kollektionszahlen vor. Aussagen zur Vollstaendigkeit, Menue-Soll-Struktur,
Zuordnungsfehlern, unklaren Produkten oder erforderlichen
Kollektionsaenderungen waeren ohne API-Daten nicht belastbar und werden nicht
erfunden.

## Sichere lokale Einrichtung

1. In der Codex-Cloud-Umgebung die bestaetigte kanonische
   `*.myshopify.com`-Domain, dieselbe erwartete Shop-Domain, die erwartete
   Primaerdomain `netzer-dental.de` und eine explizite unterstuetzte API-Version
   als nicht geheime Umgebungsvariablen setzen.
2. Client ID und Client Secret der bestehenden App ausschliesslich als
   geschuetzte Secrets hinterlegen. Keine lokale `.env` ist erforderlich.
3. `bash scripts/codex_cloud_setup.sh` als Setup-Skript konfigurieren. Es erzeugt
   das kurzlebige Token im Arbeitsspeicher und liest ausschliesslich die
   Shop-Identitaet; jede Domain-Abweichung stoppt den Prozess.
4. Erst nach erfolgreichem Identitaetscheck wird das noch zu erstellende
   Phase-1-Audit mit vollstaendiger Cursor-Pagination fuer Menues samt
   Unterebenen und Linkzielen, Produkte samt geforderten Feldern und
   Kollektionen samt Regeln ausgefuehrt. Bei fehlendem oder mehrdeutigem
   `main-menu-ii` wird angehalten und nachgefragt.

Details und offizielle Dokumentationsverweise stehen in
[`codex-cloud-connection.md`](codex-cloud-connection.md).

## Geplanter Sicherheitsrahmen fuer Dry-Run und spaeteres Schreiben

- Analyse/Export und Schreiben bleiben getrennte Programme; Schreiben ist per
  Default deaktiviert und benoetigt eine konkrete, freigegebene Plan-ID.
- Betroffene Ausgangsobjekte werden vor Aenderungen verschluesselt bzw. in einem
  geschuetzten, von Git ignorierten Speicher gesichert.
- Der Dry-Run enthaelt pro Produkt ID, Titel, Ist-Zuordnung, vorgeschlagene
  Zuordnung, einzelne Tag-Ergaenzungen/-Entfernungen, Begruendung und Sicherheit;
  unklare Faelle und Kollektionsregel-Aenderungen werden separat ausgewiesen.
- Vor jedem spaeteren Schreiben werden gespeicherte Versionsmerkmale bzw.
  Inhalts-Hashes erneut mit Shopify verglichen. Abweichungen stoppen den Lauf.
- Mengenartige Aenderungen werden als Differenzen berechnet, damit Wiederholung
  weder Tags noch Kollektionszuordnungen dupliziert. Unbekannte Tags bleiben
  erhalten.
- Ein redigiertes Aenderungsprotokoll enthaelt keine Tokens und keine
  vollstaendigen Shop-Daten. Der Wiederherstellungsplan nutzt die Sicherung und
  inverse Einzeloperationen.
- Nach einem Schreibvorgang werden die tatsaechlichen
  Kollektionszugehoerigkeiten erneut gelesen und gegen den freigegebenen Plan
  geprueft.
- Der Schreibablauf bleibt: ausdrueckliche Planfreigabe, zehn gemeinsam
  ausgewaehlte Testprodukte, Kontrolle, erneute Freigabe, Restkatalog.
  Aenderungen automatischer Kollektionsregeln erhalten eine eigene Freigabe.
