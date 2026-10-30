# Konzept: heruntergeladene Dateien als Agentenkontext lesen

Stand: 30. Oktober 2026. Die erste Umsetzung ist jetzt vorhanden; die ursprüngliche Bestandsaufnahme und die weitergehenden Ziele bleiben unten zur Einordnung erhalten.

## Umgesetzt

`read_file` liest Downloads über eine gemeinsame Reader-Registry mit `FileExtension`-Enum. Native Parser erschließen Dokumente, Tabellen, PDF, E-Books, E-Mails und Archive; Bilder und Scans erhalten lokale OCR. Große konvertierte Ergebnisse werden unabhängig vom Antwortbudget vollständig für die gewählte Ansicht unter `.content/` gespeichert. Seiten, Blätter, Zellbereiche und verschachtelte Anhänge bleiben gezielt abrufbar.

Die Parser gehören zur normalen, gelockten Installation. XLS verwendet `xlrd`, ODS `odfpy`; es gibt keine alternative Calamine-Installation. RapidOCR, ONNX Runtime und PDFium bilden einen lokalen OCR-Weg. Audio/Video liefern vorerst nur Metadaten. Nicht unterstützte Binärformate und nicht erschlossene Teile erscheinen ausdrücklich im Ergebnis.

Bedienung und genaue Grenzen stehen in der [README](README.md). Die [Validierung](file-reader-validation.md) beschreibt Tests, öffentliche Beispieldokumente und gefundene Fehler. Webseiten-Spill bleibt ein eigener, noch nicht umgesetzter Teil des [Webseiten-Konzepts](content-extraction-concept.md).

## Ziel

Der Agent soll möglichst viele typische Downloads selbst einlesen können: als Text, Markdown oder strukturierte Daten. Der reguläre Leseweg benötigt keinen Browser und keine vom Agenten aufgenommenen Screenshots.

Für Scans darf intern eine OCR-Pipeline Seiten rendern und den erkannten Text zurückgeben. Das ist eine Verarbeitung der Datei; der Agent muss dafür keinen PDF-Viewer bedienen.

Der Wunsch nach breiter Abdeckung bedeutet unterschiedliche Lesemöglichkeiten je Format. Ein Tabellenblatt soll als Tabelle mit Zellbezügen zugänglich sein, eine Aufnahme als Transkript und ein Archiv als navigierbare Sammlung. Für Formate ohne geeigneten Inhaltsparser müssen Metadaten und die tatsächliche Einschränkung sichtbar bleiben.

## Bestandsaufnahme vor der Umsetzung

Downloads werden bereits verfolgt und im Workspace abgelegt. Der Agent sieht Status, Dateinamen und Pfade und kann Dateien über `read_file` lesen. Dafür existieren Tests einschließlich eines Agentenablaufs für einen PDF-Download.

| Format | Aktueller Leseweg in der Standardzusammenstellung | Einschränkung |
| --- | --- | --- |
| Markdown, TXT, Quelltext, Logs | UTF-8-Text, abschnittsweise mit `offset` und `next_offset` | Andere Zeichencodierungen werden nicht automatisch aufgelöst. |
| CSV, TSV, JSON, XML, HTML | Als UTF-8-Rohtext lesbar | Keine allgemeine strukturierte Datenabfrage oder Tabellenansicht. |
| PDF mit Textschicht | `pypdf` extrahiert den Text einer gewählten Seite; Seitenzahl und Fortsetzung sind vorhanden | Keine strukturierte Repräsentation von Tabellen, Abbildungen und Layout. |
| Gescannte PDF und Bilder | Kein OCR-Leseweg implementiert | Der aktuelle Hinweis verweist auf Browser und Screenshot. |
| Excel und andere Office-Dateien | Kein eigener Inhaltsparser | Binärdateien laufen in den allgemeinen Textleser und werden abgewiesen. |
| Archive, E-Books, E-Mails, Audio, Video und spezielle Datenformate | Keine entsprechenden Inhaltsleser in der Standardzusammenstellung | Download vorhanden, Inhalt für den Agenten weitgehend unzugänglich. |

Das ist insbesondere für Excel ein echter blinder Fleck. `open_file` öffnet lediglich eine lokale Datei im Browser; es ergänzt keinen fehlenden Office-Parser.

Verifiziert wurden die vorhandenen Tests in `tests/test_files.py` und `tests/test_download_integration.py`: **21 bestanden, einer übersprungen**. Das bestätigt die vorhandenen Funktionen, nicht die hier vorgeschlagenen Erweiterungen.

Weitere bestehende Grenzen: `read_file` lehnt Dateien oberhalb des konfigurierten `max_file_bytes` ab, standardmäßig 50 MB. Ein entfernter Browser benötigt heute einen ausdrücklich konfigurierten gemeinsamen Dateisystemzugriff. Ein Pfad auf dem Browserhost allein macht die Datei noch nicht für den Agentenhost lesbar.

## Eine gemeinsame Leseschnittstelle

`read_file` bleibt der naheliegende Einstieg. Dahinter erkennt eine Formaterkennung den tatsächlichen Inhalt und wählt einen passenden Leser. Dateiendung, MIME-Angabe und Dateisignatur werden gemeinsam betrachtet. Ein XLSX- oder DOCX-Container darf beispielsweise nicht nur als beliebiges ZIP-Archiv erscheinen.

Der Agent muss die Parser-Auswahl nicht selbst übernehmen. Bei Dokumenten liest er Seiten oder Abschnitte, bei Tabellen Blätter und Bereiche, bei Archiven einzelne Einträge. Die erste Antwort soll die vorhandene Struktur und eine kleine, brauchbare erste Ansicht liefern. Weitere Inhalte bleiben gezielt abrufbar.

Ein zusätzlicher Überblicksaufruf kann später sinnvoll sein. Für den ersten Entwurf braucht es aber keine große Sammlung neuer Tools je Dateiendung.

### Downloads und Webseiten unterscheiden sich beim Speichern

Eine heruntergeladene Datei ist bereits dauerhaft als vollständige Quelle vorhanden. Es ist deshalb nicht nötig, jede große Arbeitsmappe oder jede Stunde Audio vor dem ersten Lesezugriff vollständig umzuwandeln. Ein Leser kann Seiten, Blätter oder Zeitabschnitte bei Bedarf verarbeiten und die Ergebnisse wiederverwenden.

Bei der Webseiten-Extraktion muss hingegen der erfasste Inhalt gesichert werden, weil die Live-Seite sich verändert. Beide Wege sollen anschließend über dieselbe Dateileseschicht zugänglich sein.

Es gibt keinen stillen Zeichen-Cutoff für den zugänglichen Inhalt. Begrenzt wird die einzelne Kontextantwort. Große abgeleitete Ergebnisse werden gespeichert beziehungsweise in geordnete Teile aufgeteilt; der Agent erhält Pfad, Übersicht und Fortsetzung. Das Original bleibt erhalten.

## Abzudeckende Formatfamilien

Die Tabelle beschreibt den gewünschten Ausbau. Sie ist keine Behauptung, dass die Formate heute implementiert sind oder jeder Inhalt verlustfrei in Text überführbar wäre.

| Familie und Beispiele | Gewünschte lesbare Repräsentation | Zu erhaltende Besonderheiten |
| --- | --- | --- |
| Text: TXT, MD, LOG, Quelltext, Konfigurationsdateien, JSONL | Originalnaher Text mit Abschnitten oder Zeilenbezügen | Zeichencodierung, Zeilenumbrüche und nachvollziehbare Fortsetzung. |
| Strukturierte Texte: JSON, XML, YAML, CSV, TSV | Übersicht, Schema und gezielt lesbare Einträge oder Tabellenbereiche | Rohtext bleibt verfügbar; keine stillen Typumwandlungen oder abgeschnittenen Tabellen. |
| Web-Exporte: HTML, XHTML, MHTML/MHT | Inhalt mit Überschriften, Links und Tabellen | Quellenbezug und eingebettete Ressourcen; Skripte werden nicht zur Dateilektüre ausgeführt. |
| PDF, einschließlich Scans und gemischter Seiten | Seitenweiser Text, Tabellen und bei Bedarf OCR | Seitenbezug, Lesereihenfolge, OCR-Kennzeichnung und erkennbare Lücken. |
| Tabellen: XLSX, XLS, XLSM, XLSB, ODS | Blattübersicht und Tabellenbereiche mit Zelladressen | Werte, Formeln, Datentypen, Einheiten, verbundene Zellen und verborgene Bereiche ausdrücklich behandeln. |
| Textdokumente: DOCX, DOC, ODT, RTF, Pages | Abschnitte, Überschriften, Listen und Tabellen | Fußnoten, Kommentare, Änderungen und eingebettete Inhalte je nach verfügbarem Parser ausweisen. |
| Präsentationen: PPTX, PPT, ODP, Keynote | Folienweise Text, Tabellen und verfügbare Sprechernotizen | Foliennummern; textlose Diagramme oder Bilder als noch nicht erschlossenen Inhalt melden. |
| E-Books: EPUB, FB2 und gegebenenfalls MOBI/AZW | Inhaltsverzeichnis und Kapitel | DRM- oder Passwortschutz nicht als leeren Inhalt darstellen. |
| E-Mail und Kalender: EML, MSG, MBOX, ICS, VCF | Nachrichten, Termine und Kontakte mit Feldern | Anhänge getrennt auffindbar; Nachrichtengrenzen, Absender und Datumsangaben erhalten. |
| Archive: ZIP, TAR, GZ, 7Z, RAR und verschachtelte Archive | Inhaltsverzeichnis und gezielt lesbare Einträge | Namen, Größen, Verschachtelung und Einschränkungen; Inhalte nicht pauschal zusammenkleben. |
| Bilder: PNG, JPEG, TIFF, WEBP, GIF, SVG | Metadaten und erkannter Text; gegebenenfalls gesonderte Bildbeschreibung | OCR ist keine vollständige Beschreibung eines Fotos oder Diagramms. SVG kann zusätzlich direkt lesbare Texte enthalten. |
| Audio und Untertitel: WAV, MP3, M4A, FLAC, OGG, SRT, VTT | Transkript beziehungsweise vorhandene Untertitel mit Zeitbezügen | Erkanntes und tatsächlich vorhandenes Transkript unterscheiden; Sprecher nur ausweisen, wenn ermittelt. |
| Video: MP4, WEBM, MOV, AVI | Untertitel, Tontranskript und Metadaten; weitere Bildanalyse gesondert | Ein Tontranskript erschließt nicht automatisch sichtbare Abläufe, Diagramme oder Bildschirmtexte. |
| Datenbestände: SQLite, Parquet, Arrow/Feather, DBF, Avro | Schema, Tabellenübersicht und lesbare Bereiche | Datentypen und strukturierter Zugriff statt eines gigantischen Textdumps. |
| Geo- und Wissenschaftsdaten: GeoJSON, KML, GPX, Shapefile, NetCDF, HDF5 | Metadaten, Schema, Einheiten und gezielt zugängliche Datensätze | Mehrdimensionale Daten und Geometrien brauchen eigene Leser; keine pauschale Markdown-Vollständigkeit zusagen. |
| Spezialformate: CAD, 3D-Modelle, Fonts, Disk-Images und unbekannte Binärdateien | Zunächst verlässliche Typ- und Metadaten; Inhaltsleser nur bei vorhandener Unterstützung | Das Extrahieren von Metadaten ist keine vollständige Inhaltserschließung. |
| Programme, Installer, Skripte und Makrocontainer | Text lesen, falls vorhanden; sonst Metadaten und gegebenenfalls Containerinventar | Die Datei zum Lesen nicht installieren oder ausführen; Makros nicht aktivieren. |

## Wichtige Details für Excel

Excel sollte nicht nur zu irgendeiner Markdown-Tabelle werden. Die erste Ansicht nennt die Blätter, deren relevante Bereiche und vorhandene Einschränkungen. Anschließend kann der Agent beispielsweise einen Bereich aus einem bestimmten Blatt lesen.

Zelladressen und Blattnamen müssen erhalten bleiben. Leere Zellen dürfen nicht unbemerkt zu Null werden. Datumsangaben, Währungen und Prozentwerte brauchen ihren Typ beziehungsweise ihre Darstellung. Verbundene Zellen und verborgene Blätter oder Zeilen müssen nachvollziehbar behandelt werden.

Formeltext und gespeicherter Ergebniswert sind unterschiedliche Informationen. Ein gespeicherter Wert kann fehlen oder veraltet sein. Die Lesefunktion soll keine neu berechneten Werte behaupten und keine externen Verknüpfungen aktualisieren. Eine Berechnungs- oder Analyseumgebung wäre eine eigene Erweiterung.

Für viele alltägliche Aufgaben reichen dann Blattübersicht, gezielte Bereiche und deren Kontext. Ein kompletter Workbook-Dump in einer einzigen Modellantwort wäre teuer und schwer überprüfbar.

## Bibliotheken: hier lohnt externe Hilfe

Für PDF, Office-Container, Legacy-Formate, OCR und Medien würde ich keine eigenen Binärparser schreiben. Die eigene Arbeit gehört in Formaterkennung, Routing, einheitliche Ergebnisse und die gezielte Bereitstellung für den Agenten.

Die folgenden Kandidaten wurden zunächst anhand ihrer offiziellen Dokumentation und ausgewählten Quellcodes eingeordnet. Die Umsetzung verwendet spezialisierte Parser, damit Zellbezüge, Selektoren und Fehlerzustände erhalten bleiben. MarkItDown, Docling und Tika wurden nicht als zusätzliche Backends installiert; die Tabelle dokumentiert die ursprüngliche Auswahlprüfung.

| Kandidat | Interessanter Nutzen | Offene Prüfung vor einer Auswahl |
| --- | --- | --- |
| Microsoft MarkItDown | Python-Konvertierung vieler häufiger Downloads zu Markdown, unter anderem Office, PDF, EPUB und ZIP; optionale Formatabhängigkeiten | Ausgabequalität, große Dateien, Excel-Semantik und tatsächlich verfügbare OCR-/Transkriptionspfade. |
| Docling | Einheitliches Dokumentmodell, viele Dokumentformate sowie OCR- und strukturierte Ausgabewege | Modell- und Laufzeitbedarf, konkrete Tabellentreue und lokale Verarbeitung auf unseren Zielsystemen. |
| Apache Tika | Sehr breite Erkennung sowie Text- und Metadatenextraktion; interessant für seltenere und ältere Formate | Zusätzliche Java-Prozessintegration und die Genauigkeit der jeweiligen Inhaltsrepräsentation. |
| Spezialisierte Formatbibliotheken | Präziser Zugriff auf Zellen, Seiten, Archive oder Datensätze | Welche davon gegenüber einem Sammelkonverter tatsächlich benötigte Struktur erhalten. |

MarkItDown ist ausdrücklich auf LLM-lesbare Markdown-Ausgabe ausgerichtet und unterstützt optionale Abhängigkeiten für einzelne Formate. Seine Projektmetadaten kennzeichnen es derzeit als Beta. Es sollte deshalb anhand unserer Anforderungen geprüft und nicht pauschal als fertige Formatgarantie eingebaut werden. Quellen: [Projekt und Formate](https://github.com/microsoft/markitdown), [Paketdefinition](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/pyproject.toml).

Ein konkreter Grund für die Excel-Prüfung: Der untersuchte XLSX-Konverter liest sämtliche Blätter über Pandas und erzeugt daraus HTML beziehungsweise Markdown. Er stellt in diesem Konvertierungspfad keine vollständige Formel- und Zelladressansicht bereit. Das ist für eine schnelle Textansicht nützlich, ersetzt aber nicht automatisch den oben beschriebenen Tabellenleser. Quelle: [XLSX-Konverter](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_xlsx_converter.py).

Docling dokumentiert unter anderem PDF, Office, OpenDocument, E-Books, Bilder und weitere Medien. Einige Formatwege benötigen zusätzliche Komponenten; die bloße Nennung einer Endung bedeutet daher nicht, dass jede Standardinstallation diese Datei bereits verarbeiten kann. Quelle: [Unterstützte Formate](https://docling-project.github.io/docling/usage/supported_formats/).

Tika dokumentiert breite Datei-Erkennung, Text-/Metadatenextraktion sowie CLI- und Serverbetrieb auf Java-Basis. Es ist damit ein interessanter Kandidat für zusätzliche Formatabdeckung, aber keine Garantie für die vollständige Semantik jedes Dateityps. Quelle: [Apache Tika](https://github.com/apache/tika).

Vorläufige Richtung: einfache Textdateien direkt lesen, für Dokumente und Tabellen etablierte Parser beziehungsweise geeignete Sammelkonverter verwenden und aufwendige OCR-/Medienwege als eigene Fähigkeiten behandeln. Die breite Formatliste rechtfertigt keinen ungetesteten Import aller verfügbaren Erweiterungen.

## Ehrliche Rückmeldungen statt blinder Flecken

Jeder Leser muss zwischen mindestens diesen Ergebnissen unterscheiden:

- Inhalt verfügbar, mit Angaben zum erschlossenen Umfang und zur Fortsetzung.
- Inhalt teilweise verfügbar, mit konkreten fehlenden Teilen.
- Nur Metadaten verfügbar.
- Format erkannt, aber der benötigte Leser fehlt.
- Datei geschützt, beschädigt oder Verarbeitung fehlgeschlagen.

Davon unabhängig bleibt die Ausgabeform: direkt enthalten, als abgeleitete Datei gespeichert oder in adressierbaren Abschnitten verfügbar.

Fehlende OCR, ein unbekanntes Format oder ein kaputter Tabellenparser dürfen nicht in einer scheinbar erfolgreichen leeren Antwort enden. Ein Texttranskript eines Videos darf ebenso wenig als vollständige Erschließung des Videos gelten. Generierte Beschreibungen und Zusammenfassungen sind von extrahiertem Originaltext zu unterscheiden.

Die heutigen pauschalen Empfehlungen „im Browser öffnen“ oder „Screenshot verwenden“ müssen bei diesen Fehlerfällen durch einen passenden Hinweis ersetzt werden. Eine freiwillige visuelle Ansicht kann bestehen bleiben; sie ist keine Voraussetzung für den regulären Dateileseweg.

## Große Dateien, Archive und Erreichbarkeit

Antwortbudgets beschränken den Kontextumfang, nicht die grundsätzliche Erreichbarkeit weiterer Inhalte. Seiten, Bereiche, Nachrichten und Archiveinträge erhalten nachvollziehbare Bezugspunkte. Eine abgeschnittene Vorschau braucht eine explizite Fortsetzung.

Die bestehende 50-MB-Lesegrenze darf dabei nicht unbemerkt den neuen Weg blockieren. Metadaten und strukturierter Zugriff sollten auch bei großen Quellen möglich sein, soweit der jeweilige Leser sie verarbeiten kann. Ein tatsächlicher Ressourcenabbruch muss ausdrücklich gemeldet werden.

Archive werden zunächst aufgelistet und anschließend gezielt gelesen. Entpackte Pfade bleiben im vorgesehenen Workspace. Rekursion und expandierende Datenmengen benötigen nachvollziehbare Arbeitsgrenzen; ein dadurch unerschlossener Rest wird ausgewiesen. Ein defekter Anhang darf die übrigen Einträge nicht unsichtbar machen.

Bei Remote-Browsern muss die Datei auf dem Rechner der Lesepipeline verfügbar sein, etwa über den bereits konfigurierten gemeinsamen Speicher oder einen gesonderten Transferweg. Dieser Transport ist Teil der Download-Integration und lässt sich nicht durch eine andere Parser-Bibliothek ersetzen.

## Ausbau in sinnvoller Reihenfolge

1. Den aktuellen Text-/PDF-Leseweg und seine Fortsetzung erhalten. Formaterkennung und klare Fähigkeiten-/Fehlermeldungen ergänzen.
2. CSV/TSV sowie Excel, DOCX und PPTX mit einer gezielten Dokumenten-/Tabellenpipeline erschließen. Die Kandidaten an realen und problematischen Dateien vergleichen.
3. Scans/OCR, OpenDocument, ältere Office-Dateien, EPUB, E-Mails und Archive ergänzen. Anhänge durch dieselbe Leseschicht führen.
4. Audio-/Videotranskription und spezialisierte Datenleser nachziehen. Für die übrigen Formate Typ, Metadaten und die fehlende Fähigkeit zuverlässig ausgeben.

Für jede Formatfamilie braucht es passende Beispiele: mehrere Blätter und Formeln, textlose PDF-Seiten, Nachrichten mit Anhängen, Archive mit unterschiedlichen Dateien sowie beschädigte oder geschützte Quellen. Ein Test, der nur eine Datei öffnet, belegt noch keine brauchbare Inhaltserschließung.

Die Akzeptanzbedingung ist: Der Agent kann unterstützte Inhalte als Kontext lesen und weitere Teile gezielt anfordern. Für jeden nicht erschlossenen Teil ist erkennbar, was fehlt und warum. Die bloße Existenz einer heruntergeladenen Datei zählt nicht als erfolgreiche Inhaltsverarbeitung.
