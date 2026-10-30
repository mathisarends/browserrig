# Dateileser: Umsetzung und Validierung

Stand: 30. Oktober 2026.

## Struktur und Installation

`read_file` ist der gemeinsame Einstieg. `FileExtension` benennt die bekannten Endungen; die Registry in `browserrig/files/formats.py` verbindet Formate mit einer einheitlichen Reader-Signatur und ihren Selektoren. Die Zuordnung benötigt keine wachsende Parser-`if`-Kette. Signaturen und Container-Inhalte erkennen unter anderem PDF und Office-Dateien auch bei falschen Download-Endungen.

Die Installation erfolgt mit `uv sync --locked`. Es gibt keine optionalen Parser-Pakete oder konkurrierenden Laufzeitpfade. Der Lockfile hält die tatsächlich geprüften Versionen fest. Die meisten Dokumentbibliotheken sind langjährig etablierte Projekte; Alter oder ein Stable-Label allein garantieren trotzdem keine fehlerfreie Extraktion.

| Aufgabe | Verwendete Bibliothek |
| --- | --- |
| HTML und Zeichencodierung | Beautiful Soup, markdownify, charset-normalizer |
| XLSX und XLS | openpyxl und xlrd |
| OpenDocument | odfpy |
| DOCX, PPTX, RTF | python-docx, python-pptx, striprtf |
| PDF-Text und Seitenrendering | pypdf und pypdfium2 |
| Lokale OCR | RapidOCR 3.9.2, ONNX Runtime 1.30.0, OpenCV, Pillow |
| Medienmetadaten | Mutagen |
| Sichere XML-Verarbeitung | defusedxml |
| Archive, E-Mail, SQLite | Python-Standardbibliothek |

Calamine wurde nicht übernommen; für XLS genügt xlrd, für ODS der bereits benötigte OpenDocument-Parser. OCR verwendet gebündelte Modelle auf der CPU. Der Agent erhält erkannten Text, ohne einen Browser-Viewer oder Screenshots bedienen zu müssen. Eine plattformübergreifende Installationsgarantie folgt daraus nicht: geprüft wurden lokale Windows-Installationen mit Python 3.12 und 3.14.

## Automatisierte Prüfungen

| Prüfung | Ergebnis |
| --- | --- |
| Reguläre Suite, Python 3.14 | 291 bestanden, 2 übersprungen; 92 Chrome-Tests regulär abgewählt |
| Download-Integration mit echtem Chrome | 6 bestanden |
| Dateileser in isolierter Python-3.12-Installation aus dem Lockfile | 43 bestanden, 2 übersprungen |
| Ruff, Formatprüfung, Pylint und ty | Bestanden |
| Lockfile und `git diff --check` | Bestanden |
| Öffentlicher Korpus mit frischem Cache | 35 erwartete Ergebnisse, davon ein erwarteter Korruptionsfehler |

Die Offline-Tests erzeugen echte Formatdateien und prüfen deren Inhalt, Fortsetzung und Fehlerzustände. Abgedeckt sind unter anderem:

- Excel-Formeln mit gespeicherten beziehungsweise fehlenden Ergebnissen, Formate, verborgene Bereiche, verbundene Zellen, sehr dünn belegte Blätter sowie falsche oder fehlende Dimensionsangaben.
- Alte BIFF-XLS-Daten, ODS, CSV mit eingebetteten Zeilenumbrüchen und Trennzeichen sowie gezielte Zellbereiche.
- Verschachtelte Word-Tabellen, PowerPoint-Notizen, Kapitelreihenfolge in EPUB und E-Mail-Anhänge.
- Unicode-Fortsetzung, andere Zeichencodierungen und vollständige gespeicherte Extraktionen über dem Antwortbudget; Cache-Wiederverwendung und Änderung der Quelldatei.
- OCR aus Bilddateien und gescannten PDF-Seiten; beschädigte Dateien und unbekannte Binärformate.
- Verschachtelte Archive, CRC-Fehler, mehrdeutige Einträge, Traversal, Symlinks sowie Expansions- und Tiefengrenzen.
- Unveränderte Quelldateien und nur lesend geöffnete SQLite-Datenbanken mit NULL- und BLOB-Werten.

Zwei zusätzliche Chrome-Integrationstests prüfen einen tatsächlichen XLSX-Download und den anschließenden Agentenaufruf von `read_file`. Die Antwort enthält Zellinhalt und keine Bildnachricht; es wird keine neue Browservorschau geöffnet.

Die Windows-Symlinktests werden übersprungen, wenn dem Testprozess die dafür erforderlichen Rechte fehlen. Das ist eine verbleibende Prüfungslücke auf diesem Host.

## Öffentlicher Dokumentkorpus

Zusätzlich wurden 35 bestehende öffentliche Dokumente gelesen, mit insgesamt 68 Seiten- beziehungsweise Blattansichten. 34 Dateien lieferten die erwarteten Ergebnisse mit ihren Einschränkungen. Eine absichtlich beschädigte XLS-Datei wurde mit einem eindeutigen Korruptionsfehler abgewiesen. Das bedeutet ausdrücklich nicht, dass die 34 übrigen Dateien visuell oder semantisch vollständig erschlossen wären: bildbasierte Office-Inhalte und leere Dokumente bleiben entsprechend gekennzeichnet.

| Quelle | Dateien | Geprüfte Besonderheiten |
| --- | ---: | --- |
| [xlrd-Testdateien](https://github.com/python-excel/xlrd/tree/master/tests/samples) | 8 | BIFF-Versionen, Datumswerte, Fehlerzellen, ungleich lange Zeilen, Bildzellen, leere XLSX/ODS und beschädigte XLS |
| [python-docx-Testdateien](https://github.com/python-openxml/python-docx/tree/master/tests/test_files) | 4 | Absatz- und Tabellenreihenfolge, Abschnitte, Bilder und Dokumenttext |
| [python-pptx-Testdateien](https://github.com/scanny/python-pptx/tree/master/tests/test_files) | 5 | Gruppen, Tabellen, fehlende Beziehungen beziehungsweise Metadaten und Präsentation ohne Folien |
| [LibreOffice-Calc-Testdateien](https://github.com/LibreOffice/core/tree/master/sc/qa/unit/data) | 13 | XLSX/ODS/XLSM, Formeln, Formate, verborgene Blätter, Filter, verbundene und wiederholte Zellen sowie gespeichertes VBA-Formelergebnis |
| [Attention Is All You Need](https://arxiv.org/abs/1706.03762) | 1 | Alle 15 Seiten des heruntergeladenen Text-PDF |
| [OCRmyPDF-Testdateien](https://github.com/ocrmypdf/OCRmyPDF/tree/main/tests/resources) | 4 | CCITT, JBIG2, gedrehte und schiefe Scans mit tatsächlich erkanntem Text |

Der Korpus hat konkrete Fehler aufgedeckt, die behoben wurden: fehlende beziehungsweise falsche XLSX-Dimensionsangaben, von openpyxl abgewiesene bedingte Formatierungen trotz lesbarer Werte und sehr viele wiederholte leere ODS-Zeilen. Bedingte Formatierungen werden aus der temporären XLSX-Leseprojektion entfernt und als nicht angewandt ausgewiesen; das Original bleibt unverändert.

Die Quellen, SHA-256-Prüfsummen, erwarteten Statuswerte und ausgewählte Inhaltsmarker stehen in `tests/file_corpus.json`. Die Binärdateien werden nicht ins Repository übernommen. Der Korpuslauf ist ausdrücklich separat vom Offline-Testlauf:

```powershell
uv run --locked python tests/check_file_corpus.py "$env:TEMP/browserrig-file-corpus-20261030" --download
```

Ohne `--download` werden nur bereits vorhandene Quellen verwendet. Abweichende Prüfsummen werden abgewiesen. Jeder Reader läuft in einem eigenen Prozess mit 30 Sekunden Zeitgrenze; ein neuer Cache verhindert, dass vorherige Extraktionen die Prüfung ersetzen. Der Lauf liest alle aufgeführten Blätter beziehungsweise PDF-Seiten, folgt Fortsetzungen und prüft Inhaltsmarker. Ergebnisse ohne Dokumentvolltext stehen anschließend in `corpus-results.json` im angegebenen Verzeichnis.

## Bewusste Grenzen

`max_chars` begrenzt die einzelne Antwort. Die gespeicherte Extraktion enthält den vollständigen ausgewählten Inhalt. Bei PDF ist die Auswahl eine Seite; bei Tabellen ein Blatt oder Zellbereich; Archive und Anhänge werden gezielt geöffnet. Für sehr große oder dünn belegte XLSX-Blätter gibt es eine ausgewiesene erste Ansicht und weitere Zugriffe per `cell_range`.

Verarbeitungsgrenzen bleiben konfigurierbar: standardmäßig 50 MB Parser-Eingabe, 200 MB entpackte Inhalte und acht Container-Ebenen. Ein Ressourcenfehler wird gemeldet. Reine Textdateien werden gestreamt und unterliegen beim Lesen nicht der 50-MB-Parsergrenze. Es gibt aktuell weder eine allgemeine Prozess-Zeitgrenze für produktive Reader noch automatische Cache-Bereinigung.

OCR ist fehlbar und keine allgemeine Bildbeschreibung. PDF-Tabellen und mehrspaltige Seiten erhalten keine garantierte Lesereihenfolge. Bilder, Diagramme, Kommentare und Dokumentannotationen sind je nach Reader nur teilweise oder gar nicht erschlossen; Einschränkungen stehen strukturiert im Ergebnis. Passwörter und DRM werden nicht entschlüsselt. Excel-Formeln werden nicht berechnet; gespeicherte Werte können veraltet sein.

DOC, PPT, XLSB, MSG, 7Z, RAR, iWork, MOBI/AZW und spezialisierte binäre Datenformate haben noch keinen Inhaltsleser. Audio und Video liefern Metadaten, keine Transkripte. JSON, XML, YAML, GeoJSON und Untertitel sind als Text lesbar, erhalten aber noch keine eigenen Datenabfragen. Breite Formatabdeckung ist damit vorhanden; eine Zusage für jedes herunterladbare Dokument wäre weiterhin unzutreffend.
