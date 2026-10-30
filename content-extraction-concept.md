# Konzept: resiliente Content-Extraktion mit automatischer Dateiauslagerung

Stand: 30. Oktober 2026. Konzept und Bewertung des aktuellen Arbeitsstands; keine Implementierung.

Ergänzend beschreibt [Dateiinhalte als Agentenkontext](download-content-concept.md) den gewünschten Leseweg für Downloads: Text, PDF/OCR, Office, Tabellen, E-Books, E-Mails, Archive, Medien und Spezialformate. Dieser Weg soll ohne verpflichtende Browseransicht oder Screenshots auskommen.

## Gewünschtes Verhalten

Der Agent ruft einfach `extract_content()` auf. Er muss weder eine maximale Extraktionslänge wählen noch vorher einschätzen, wie groß eine Seite ist.

- Kleine Ergebnisse erscheinen direkt in der Tool-Antwort.
- Große Ergebnisse werden vollständig als Markdown im Agenten-Workspace gespeichert. Die Antwort enthält einen kurzen Hinweis, den Dateipfad, Metadaten und gegebenenfalls eine kleine Vorschau.
- Der Agent entscheidet anschließend selbst, ob er die Datei mit `read_file` lesen möchte. Über `offset` und `next_offset` kann er weitere Abschnitte abrufen.

**Es gibt im vorgeschlagenen Agentenvertrag kein Zeichenlimit für die Extraktion.** Eine interne Grenze für die Größe der Tool-Antwort bestimmt ausschließlich die Ausgabeform. Sie darf weder den gespeicherten Inhalt abschneiden noch spätere Frames aus der Extraktion verdrängen.

Das bisherige `max_chars` vermischt diese Aufgaben. Es sollte aus dem regulären Agentenaufruf entfallen. Falls bestehende Python-Aufrufer berücksichtigt werden müssen, braucht der bisherige Parameter eine explizite Migration; seine Bedeutung sollte nicht stillschweigend geändert werden.

## Einschätzung der bestehenden Lösung

Die Browser-Anbindung ist eine brauchbare Basis. Sie berücksichtigt isolierte Ausführung, den zusammengesetzten DOM einschließlich Slots und Shadow Roots, verfügbare Cross-Origin-Frames, Dokumentwechsel und Fehler einzelner eingebetteter Frames. Formulareingaben werden ausgelassen. Die Extraktion scrollt nicht und ersetzt keine interaktiven Elementreferenzen.

Die bestehende Absicherung durch Tests ist sinnvoll, aber noch kein Nachweis für beliebige Webseiten: Die vier Content-Integrationstests und acht Integrationstests für Sichtbarkeit und Kürzung bestehen. Die folgenden zusätzlichen Schwachstellen ergeben sich aus der Codeprüfung. Mehrere Renderer-Fehler wurden inzwischen in temporären Vergleichsversuchen reproduziert; siehe [Bibliotheksevaluation](content-extraction-library-evaluation.md). Die Aussagen zu Ressourcen und Dokumentkonsistenz beruhen weiterhin auf der Codeprüfung.

### 1. Ausgabelimit begrenzt heute bereits die Erfassung

In `browserrig/observation/content.py` wird das verbleibende Budget an das Seitenskript weitergereicht. In `browserrig/scripts/content.js` beendet dieses Budget bereits das Lesen von Text und weiteren Knoten. Ein langes Hauptdokument kann dadurch alle späteren Frame-Inhalte verdrängen.

Die aktuelle Ausgabe nachträglich in eine Datei zu schreiben würde nur den schon gekürzten Inhalt retten. Für das gewünschte Verhalten muss die Erfassung unabhängig davon weiterlaufen, ob die Inline-Antwort bereits voll ist.

### 2. Der Markdown-Renderer verliert teilweise Bedeutung

In `browserrig/scripts/content.js` werden Leerzeichen innerhalb von Links und Hervorhebungen mit `trim()` entfernt. Ein Leerzeichen, das innerhalb einer Hervorhebung an einer Wortgrenze liegt, kann dadurch verschwinden und Wörter zusammenziehen.

Bei Tabellen werden `rowspan` und `colspan` nicht aufgelöst. Zellwerte können dadurch unter der falschen Spalte stehen. Auch durchgestrichener Text und Checkbox-Zustände in Aufgabenlisten werden nicht erhalten. Das ist für einen lesenden Agenten relevant, weil Formatierung hier fachliche Bedeutung trägt.

### 3. Die Arbeitsgrenzen greifen nicht durchgängig

Die Tabellenbehandlung materialisiert alle Zeilen und Zellen, bevor die Ausgabe abschließend begrenzt wird. Zusätzlich erfasst `seed_frame` per DOMSnapshot zunächst die Dokumente einer CDP-Session. Ein kleines `max_chars` bedeutet deshalb heute keine entsprechend kleine Rechen- oder Speicherlast.

Es gibt Timeouts für einzelne Operationen und Teile der Metadatenbeschaffung, aber kein durchgängiges Budget für den gesamten Extraktionsvorgang. Ein CDP-Timeout allein garantiert außerdem nicht, dass laufendes synchrones JavaScript im Renderer beendet wird.

### 4. Die Prüfung auf Dokumentwechsel ist begrenzt

Der abschließende Vergleich der `document_id` erkennt einen Wechsel des Hauptdokuments. Er erkennt keine reine DOM-Aktualisierung, keine SPA-Navigation mit unverändertem Loader und nicht zuverlässig alle Änderungen einzelner Kinddokumente während der Gesamtextraktion.

Für eine normale Leseoperation muss kein global atomarer Snapshot über alle Browserprozesse garantiert werden. Erkennbare Wechsel sollten aber zu einer Wiederholung oder einer ausdrücklich unvollständigen Extraktion führen. URL, Titel und Inhalte dürfen nicht unbegründet als ein konsistenter Zeitpunkt beschrieben werden.

### 5. Kürzung ist nur teilweise strukturbewusst

`browserrig/scripts/lib/markdown.js` behandelt Code-Fences am Zeilenanfang. Verschachtelte Strukturen in Listen und Zitaten sowie abgeschnittene Links und Inline-Formatierungen brauchen zusätzliche Behandlung. Mit Dateiauslagerung betrifft das primär die Vorschau; das gespeicherte Dokument sollte gar nicht wegen der Antwortgröße gekürzt werden.

## Rolle externer Libraries

Die gezielte [Bibliotheksevaluation](content-extraction-library-evaluation.md) ist abgeschlossen. Meine Empfehlung ist, für den aktuellen Umfang auch den eigenen Renderer gezielt zu härten. Turndown selbst ist eine brauchbare Option; die ursprünglich vorgeschlagene Kombination mit dem originalen GFM-Plugin bringt jedoch relevante Rückschritte und lässt wesentliche Integrationsarbeit offen.

| Kandidat | Passende Aufgabe | Empfehlung |
| --- | --- | --- |
| Turndown-Kern | HTML/DOM nach Markdown; erweiterbare Regeln und bessere Behandlung mehrerer Inline- und Verschachtelungsfälle | Als spätere Option mit eigenen Tabellenregeln behalten; aktuell den vorhandenen Renderer härten. |
| Originales GFM-Plugin | Tabellen, durchgestrichener Text und Aufgabenlisten | Wegen reproduzierter Tabellenfehler und Exception bei leerer Tabelle nicht übernehmen. |
| Joplin-GFM-Fork | Weiterentwickelte GFM-Regeln und bessere Tabellenbehandlung | Besser als das Original; weiterhin Lücken, insbesondere bei `rowspan`. Aktuell kein ausreichender Gesamtvorteil. |
| Mozilla Readability | Den eigentlichen Artikel aus einer Seite auswählen | Nur für einen späteren, ausdrücklich gewählten Artikelmodus. |
| Trafilatura | Haupttext und Metadaten aus HTML in einer Python-Pipeline extrahieren | Für einen separaten Artikel- oder Dokumentenworkflow interessant; für diese Browserfunktion zunächst zusätzliche Integrationsarbeit. |

Turndown unterstützt Browserbetrieb, DOM-Eingaben und eigene Konvertierungsregeln. Die GFM-Erweiterungen ergänzen unter anderem Tabellen und Aufgabenlisten. Der direkte Vergleich von 26 HTML-Beispielen und einem Shadow-Root-Beispiel zeigt sowohl konkrete Vorteile des Kerns als auch die Grenzen der Plugins. Ausgaben, Pflegezustand und Integrationsaufwand sind in der [Bibliotheksevaluation](content-extraction-library-evaluation.md) dokumentiert. Quellen: [Turndown](https://github.com/mixmark-io/turndown), [GFM-Erweiterung](https://github.com/mixmark-io/turndown-plugin-gfm).

Readability dient der Artikelauswahl und verändert beim Parsen den übergebenen DOM. Es müsste auf einer Kopie arbeiten. Für den allgemeinen Browser-Agenten wäre eine automatische Artikelauswahl riskant: Relevante Navigation, Suchergebnisse oder Dashboard-Inhalte könnten entfallen. Quelle: [Mozilla Readability](https://github.com/mozilla/readability).

Trafilatura bietet Haupttextextraktion und mehrere Ausgabeformate einschließlich Markdown. Meine Einschätzung für dieses Projekt: Es würde weiterhin eine browserseitige Projektion der sichtbaren Inhalte einschließlich Shadow Roots und Frames benötigen. Quelle: [Trafilatura: Python usage](https://trafilatura.readthedocs.io/en/latest/usage-python.html).

Eine Library übernimmt nicht automatisch unsere Regeln für Sichtbarkeit, Formulareingaben, geschlossene Shadow Roots, Frames und Dokumentwechsel. Die sinnvolle Grenze liegt zwischen browserseitiger Erfassung und Formatierung: Erst die relevanten Inhalte samt Struktur erfassen, anschließend in einem vom Live-DOM getrennten Modell konvertieren. Ein bloßes `outerHTML` würde einen Teil der bestehenden Fähigkeiten verlieren.

## Ablauf der automatischen Dateiauslagerung

1. Aktuellen Dokumentzustand und erreichbare Frames feststellen.
2. Die bereits geladenen, nach den bestehenden Sichtbarkeitsregeln lesbaren Inhalte erfassen. Die Inline-Grenze beeinflusst diesen Durchlauf nicht.
3. Solange das Ergebnis klein bleibt, kann es für eine direkte Antwort gepuffert werden. Bei Überschreiten der Antwortgrenze wird in eine temporäre Datei im Workspace gewechselt und die Erfassung fortgesetzt.
4. Dokumentwechsel und sonstige Einschränkungen prüfen. Erst anschließend das fertige Artefakt veröffentlichen.
5. Entweder das kleine Ergebnis oder einen kompakten Dateiverweis zurückgeben.

Ein möglicher Startwert für die Inline-Grenze wären etwa 20.000 Zeichen. Das ist eine interne Ausgabeentscheidung und sollte später anhand der Kontextkosten geprüft werden. Große Ergebnisse brauchen keine lange Vorschau, die den Kontext erneut füllt.

Der Agent soll die Datei nicht selbst über `write_file` anlegen müssen: Dann müsste der vollständige Inhalt vorher bereits durch den Modellkontext laufen. Die Auslagerung gehört in die Tool-Implementierung.

Eine große Extraktion sollte auch intern nicht mehrfach als riesiger String aufgebaut werden. Die Ausgabe lässt sich zunächst mindestens frameweise schreiben; für sehr große Einzeldokumente ist eine abschnittsweise Verarbeitung sinnvoll. Das Dateisystem allein behebt weder die Speicherlast im Browser noch die eines vollständig vorab aufgebauten Python-Strings.

## Vertrag der Tool-Antwort

Die Antwort muss zwei voneinander unabhängige Dinge beschreiben:

- **Bereitstellung:** Inhalt direkt enthalten oder in einer Datei gespeichert.
- **Vollständigkeit:** Extraktion im beschriebenen Umfang vollständig oder mit konkreten Einschränkungen unvollständig.

Ein ausgelagertes, vollständig erfasstes Ergebnis ist nicht „truncated“. Die Antwort wurde lediglich auf einen Dateiverweis verkürzt. Wenn dagegen ein Frame nicht erreichbar war, bleibt diese Einschränkung auch bei vorhandener Datei bestehen.

Sinnvolle Informationen sind Titel, Quell-URL, Erfassungszeitpunkt, Dateipfad bei Auslagerung, Größe und konkrete Einschränkungen. Eine kurze Inhaltsübersicht kann später helfen; für die erste Version ist sie nicht erforderlich.

Beispiel einer normalen ausgelagerten Antwort:

> Die Extraktion ist für die erreichbaren, geladenen DOM-Inhalte vollständig. Das Ergebnis ist zu groß für die direkte Ausgabe und wurde unter `extractions/<id>.md` gespeichert. Bei Bedarf mit `read_file` lesen; für weitere Abschnitte dem zurückgegebenen `next_offset` folgen.

Bei einer unvollständigen Extraktion muss die Antwort stattdessen ausdrücklich sagen, welche Inhalte fehlen. Die Einschränkungen gehören sowohl in die Tool-Antwort als auch in die Datei. Ein Lesender darf nicht erst das Dateiende erreichen müssen, um zu erfahren, dass die Erfassung unvollständig ist.

## Einbindung in das bestehende Dateisystem

Die vorhandene Grundlage passt bereits:

- `browserrig/files/system.py` stellt einen Workspace und eingeschränkte Pfadauflösung bereit.
- `read_file` liest UTF-8 abschnittsweise und liefert `next_offset`.
- `FileTools` ist in der normalen Plugin-Zusammenstellung bereits enthalten.

Extraktionen sollten einen eigenen Ordner im konfigurierten Workspace verwenden, beispielsweise `extractions/<id>.md`. Die ID wird intern erzeugt. Wiederholte Extraktionen erzeugen neue Dateien, damit spätere Lesezugriffe einen stabilen Inhalt sehen. Titel und URL stehen im Dokument und bestimmen keinen frei wählbaren Dateipfad.

Die Datei enthält den Markdown-Inhalt einschließlich Quellenzuordnung der Frames und Erfassungsmetadaten. Sie muss nach einer Browsernavigation weiterhin lesbar bleiben. Ein `read_file`-Aufruf liest immer dieses gespeicherte Ergebnis und löst keine neue Extraktion aus.

Zwei bestehende Eigenschaften müssen dabei berücksichtigt werden:

1. Bei `ConnectBrowser` kann heute der lokale Workspace fehlen. Für die Standardzusammenstellung sollte deshalb ein lokaler Artefakt-Workspace auf dem Agentenhost verfügbar sein. Ohne lesbaren Speicherort darf die Antwort keine erfolgreiche Auslagerung behaupten.
2. Das Dateisystem begrenzt einzelne Dateien standardmäßig auf 50 MB. Eine größere Datei zu schreiben reicht nicht, wenn `read_file` sie anschließend ablehnt. Für Extraktionsartefakte müssen Writer und Reader zusammenpassen, etwa durch mehrere geordnete Markdown-Dateien mit einem kleinen Index bei sehr großen Ergebnissen. Eine Dateiaufteilung begrenzt nicht die gesamte Extraktionslänge.

Temporäre Dateien dürfen bei Schreibfehlern oder Abbruch nicht als fertiges Ergebnis erscheinen. Eine verwertbare Teilerfassung kann separat bereitgestellt werden, muss dann aber ausdrücklich unvollständig sein. Bereits zurückgegebene Dateien dürfen während der Sitzung nicht unbemerkt entfernt oder überschrieben werden.

## Was „ohne Extraktionslimit“ bedeutet

Es gibt keinen regulären Zeichen-Cutoff, durch den der Agent einen unbekannten Rest verliert. Trotzdem sollte eine beschädigte Seite den Browser nicht unbegrenzt blockieren können. Technische Abbrüche wegen eines Dokumentwechsels, fehlenden Speichers oder eines nicht fortschreitenden Vorgangs bleiben möglich. Sie sind Fehler beziehungsweise ausdrücklich unvollständige Ergebnisse und kein verdecktes Längenlimit.

Die heutigen Grenzen von 50.000 besuchten Knoten, 128 Ebenen sowie Frame-Anzahl und Frame-Tiefe müssen in diesem Zusammenhang überprüft werden. Sie unverändert beizubehalten und nur `max_chars` zu entfernen würde noch keine vollständige Erfassung großer Seiten ergeben.

„Vollständig“ bezieht sich auf die bereits geladenen und mit dieser Funktion lesbaren DOM-Inhalte. Die Funktion lädt keine weiteren Seiten, scrollt nicht durch virtualisierte Listen und erzeugt keinen Text aus Canvas-Pixeln. Diese vorhandene fachliche Reichweite sollte erhalten und klar beschrieben werden.

## Sinnvolle Umsetzungsschritte nach Freigabe des Konzepts

1. Antwortvertrag und automatische Dateiauslagerung festlegen; die bisherige Begrenzung des Extraktionsinhalts davon lösen.
2. Speicherung und `read_file` gemeinsam betrachten, einschließlich fehlendem Workspace, Dateigrößen und stabilen Artefakten.
3. Die reproduzierten Renderer-Schwächen gezielt beheben. Die Bibliotheksevaluation ist abgeschlossen; die Browser-Erfassung bleibt erhalten.
4. Gezielte Integrationstests ergänzen: Inhalte hinter der bisherigen Grenze, große Frame-Inhalte, korrektes Nachlesen der Datei, Unicode-Offsets, Schreibfehler und Dokumentwechsel. Für den Renderer zusätzlich Wortabstände, komplexe Tabellen und verschachtelte Codeblöcke prüfen.

Die zentrale Akzeptanzbedingung ist: Ein Inhalt hinter der Inline-Grenze ist nach erfolgreicher Extraktion über die gespeicherte Datei erreichbar. Bei einem tatsächlichen Erfassungsfehler ist er ausdrücklich als fehlend ausgewiesen.
