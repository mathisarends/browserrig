# Bibliotheksevaluation für die Content-Extraktion

Stand: 30. Oktober 2026. Untersuchung und temporäre Vergleichsversuche; keine Änderung der Implementierung oder der Projekt-Abhängigkeiten.

## Entscheidung

**Für Browserrig würde ich aktuell den eigenen Renderer gezielt härten und keine neue Konverter-Abhängigkeit hinzufügen.**

Turndown selbst ist ein brauchbarer, gepflegter Markdown-Konverter und liefert bei mehreren unserer Fehler bessere Ergebnisse. Die ursprünglich vorgeschlagene Kombination mit dem originalen GFM-Plugin erfüllt unseren Anspruch jedoch nicht. Der Joplin-Fork verbessert die Tabellenbehandlung deutlich, deckt aber ebenfalls nicht alle benötigten Fälle ab.

Meine Abwägung: Die Browser-Erfassung und unsere inhaltlichen Regeln bleiben in jeder Variante eigene Arbeit. Für Tabellen bleibt ebenfalls eigener Aufwand. Gleichzeitig benötigt eine Turndown-Integration eine zusätzliche, vom Live-DOM getrennte Projektion unserer Inhalte. Die belegten Vorteile rechtfertigen für den derzeitigen Funktionsumfang diesen zusätzlichen Übergang noch nicht ausreichend.

Das ist eine Entscheidung über die Passung zu Browserrig. Sie ist kein allgemeines Urteil, dass Turndown ungeeignet oder grundsätzlich instabil wäre.

## Was tatsächlich geprüft wurde

Geprüfte veröffentlichte Pakete:

| Paket | Version | Verwendung im Vergleich |
| --- | --- | --- |
| `turndown` | 7.2.4 | Browser und Node |
| `turndown-plugin-gfm` | 1.0.2 | Browser und Node, mit Turndown 7.2.4 |
| `@joplin/turndown-plugin-gfm` | 1.0.68 | Browser und Node, mit Turndown 7.2.4 |
| `@joplin/turndown` | 4.0.86 | Zusätzlich in Node mit dem Joplin-Plugin |

Dazu wurden Paketmetadaten, Releases, relevanter Quellcode und ausgewählte Fehlerberichte geprüft. Die Pakete wurden mit deaktivierten Installationsskripten ausschließlich in einem temporären Verzeichnis installiert.

26 gezielt gewählte Beispiele wurden mit unserem Renderer und den beiden Plugin-Varianten in einem echten Chrome-DOM verglichen. Hinzu kam ein Beispiel mit einem geschlossenen Shadow Root. Die Node-Vergleiche verwendeten dieselben 26 HTML-Beispiele. Konfiguriert waren ATX-Überschriften und Code-Fences, damit voreingestellte Formatierungsstile den Vergleich nicht verzerren.

Das ist eine Prüfung konkreter Anforderungen und Fehlerfälle, kein repräsentativer Qualitätsbenchmark über das gesamte Web. Verglichen wurden die Ausgaben unveränderter Bibliotheken. Eine vollständig angepasste Browserrig-Integration wurde nicht gebaut.

## Stabilität und Pflege

### Turndown-Kern: ausreichend belastbar als Kandidat

Die aktuelle veröffentlichte Version ist 7.2.4. Das GitHub-Release stammt vom 3. April 2026; auf dem Hauptzweig gab es weitere Wartung im September. Der Code enthält eigene Regeln für Wortabstände, Verschachtelung, Escaping und variable Code-Fences. Tests für Konvertierung und interne Hilfsfunktionen sind vorhanden. Quellen: [Release 7.2.4](https://github.com/mixmark-io/turndown/releases/tag/v7.2.4), [Commit-Historie](https://github.com/mixmark-io/turndown/commits/master/), [Tests](https://github.com/mixmark-io/turndown/tree/master/test).

Die Version 7.2.4 nahm eine Änderung aus 7.2.3 am selben Tag zurück. Das zeigt sowohl, dass Regressionen vorkommen, als auch, dass sie korrigiert werden. Eine feste Version und eigene Integrationstests wären weiterhin nötig. Aus der bloßen Existenz von Tests leite ich keine Garantie für unseren Anwendungsfall ab. Quelle: [Release-Änderungen](https://github.com/mixmark-io/turndown/releases).

Der Browser-Build ist im geprüften Paket rund 26,7 KB unminifiziert groß und kann ohne Node-Laufzeit im Browser ausgeführt werden. Die Node-Variante benötigt zusätzlich Domino; diese Abhängigkeit muss nicht in unsere Browser-Ausführung gelangen. Größe und Laufzeitabhängigkeiten sind hier deshalb kein entscheidendes Gegenargument. Quellen: [Paketdefinition](https://github.com/mixmark-io/turndown/blob/v7.2.4/package.json), [Browser-Nutzung](https://github.com/mixmark-io/turndown#installation).

### Originales GFM-Plugin: für uns keine gute Wahl

Der letzte Commit auf dem Hauptzweig stammt vom 11. Mai 2018 und trägt die Version 1.0.2. Das Alter allein wäre für eine kleine, fertige Bibliothek kein Ausschlussgrund. Ausschlaggebend sind die weiterhin vorhandenen Fehler in unseren Versuchen: eine Exception bei einer leeren Tabelle und falsche Tabellenstruktur bei Pipes und Zeilenumbrüchen. Quelle zum Pflegezustand: [Commit-Historie](https://github.com/mixmark-io/turndown-plugin-gfm/commits/master/).

Der Quellcode behandelt weder `rowspan` noch `colspan`. Tabellen ohne erkannte Kopfzeile werden absichtlich als HTML erhalten. Das ist eine bewusste Bibliotheksentscheidung, passt aber nicht durchgängig zu unserer kompakten Markdown-Ausgabe. Quelle: [Tabellenregeln](https://github.com/mixmark-io/turndown-plugin-gfm/blob/61a981b8c6aaec73bbb8a844d9f8686d0d5f066e/src/tables.js).

### Joplin-Fork: gepflegter und besser, weiterhin Anpassungsbedarf

Joplin entwickelt seinen Fork weiter. Das veröffentlichte Plugin 1.0.68 behebt im Vergleich unter anderem Pipes, Zell-Zeilenumbrüche, Tabellen ohne Kopfzeile und den einfachen `colspan`-Fall. `rowspan` blieb im geprüften Beispiel falsch. Bei einer Tabelle mit Caption wurde zwar der Titel erhalten, aber zusätzlich eine leere Kopfzeile erzeugt und die ursprüngliche Kopfzeile als Datenzeile ausgegeben. Quellen zur Implementierung und ihrem Zweck: [Joplin-Plugin](https://github.com/laurent22/joplin/tree/dev/packages/turndown-plugin-gfm), [README](https://github.com/laurent22/joplin/blob/dev/packages/turndown-plugin-gfm/README.md).

Wichtig ist die Unterscheidung zwischen veröffentlichtem Paket und Entwicklungszweig: Zum Prüfzeitpunkt waren 1.0.68 und 4.0.86 veröffentlicht. Der Entwicklungszweig enthielt bereits höhere Versionsnummern und eine weitere Performancekorrektur. Die Bewertung der Laufzeit unten bezieht sich auf die veröffentlichten Pakete.

## Beobachtete Unterschiede

| Beispiel | Browserrig heute | Turndown + Original-GFM | Turndown + Joplin-GFM |
| --- | --- | --- | --- |
| Leerzeichen innerhalb von Hervorhebungen | Wörter werden zusammengezogen | Wortabstände erhalten | Wortabstände erhalten |
| Leerzeichen innerhalb eines Links | Wörter werden zusammengezogen | Wortabstände erhalten | Wortabstände erhalten |
| Text beginnt mit Listen-Syntax | Kann unbeabsichtigt als Liste erscheinen | Escaping vorhanden | Escaping vorhanden |
| Codeblock innerhalb einer Liste | Codezeilen verlieren die nötige Einrückung | Einrückung erhalten | Einrückung erhalten |
| Codeblock innerhalb eines Zitats | Nur der Anfang erhält den Zitatpräfix | Zitatpräfix auf allen Zeilen | Zitatpräfix auf allen Zeilen |
| Sprachangabe eines Codeblocks | Geht verloren | Erhalten | Erhalten |
| Einfaches `pre` ohne inneres `code` | Code-Fence vorhanden | Keine Code-Fence | Keine Code-Fence |
| Pipe im Tabellenwert | Korrekt escaped | Zusätzliche Spalte entsteht | Korrekt escaped |
| Zeilenumbruch in Tabellenzelle | Als `<br>` erhalten | Markdown-Zeile wird aufgebrochen | Als `<br>` erhalten |
| Tabelle ohne Kopfzeile | Markdown mit leerer Kopfzeile | HTML-Fallback | Markdown mit leerer Kopfzeile |
| Tabelle mit Caption und Kopfzeile | Titel und Kopfzeile erhalten | HTML-Fallback | Titel erhalten, zusätzliche leere Kopfzeile |
| Einfaches `colspan` | Wert landet in falscher Spalte | Wert landet in falscher Spalte | Spaltenposition im Beispiel korrekt |
| `rowspan` | Wert landet in falscher Spalte | Wert landet in falscher Spalte | Wert landet in falscher Spalte |
| Leere Tabelle vor einem Absatz | Absatz bleibt lesbar | Gesamte Konvertierung wirft Fehler | Absatz bleibt lesbar |
| Verschachtelte Tabellen | Fehlerhafte Darstellung | Fehlerhafte Darstellung | Äußere Tabelle wird verflacht |

Turndown hat damit belegte Vorteile in mehreren voneinander unabhängigen Bereichen. Diese Fehler in unserem Renderer sollten behoben werden, auch wenn wir keine Bibliothek übernehmen.

Weitere Beispiele zeigten erwartbaren Integrationsbedarf: Beide Plugin-Varianten mit dem Turndown-Kern lesen bei direkter DOM-Übergabe auch versteckte Texte und Textarea-Inhalte. Relative Links bleiben relativ. Ein geschlossener Shadow Root wird nicht erfasst. Geschlossene Details werden vollständig gelesen. Ein Bild ohne `src`, aber mit relevantem Alt-Text, verliert seinen Text.

Diese Unterschiede sind keine Behauptung, dass eine fertig angepasste Integration dieselben Fehler hätte. Sie belegen, welche Vorverarbeitung und Regeln wir bei einem Wechsel zusätzlich bereitstellen müssten. Die Unterstützung von Checkboxen ist ebenfalls kein uneingeschränkter Gewinn: Unser derzeitiger Extraktionsvertrag lässt Formularinhalte bewusst aus.

## Performance: Browser und Node getrennt betrachten

Es wurden einfache Tabellen mit zwei Spalten und kurzen Zellwerten verwendet. Im Browser ist jeweils der Median aus drei Konvertierungen nach einem Aufwärmdurchlauf angegeben. Das sind lokale Orientierungsmessungen ohne Aussage über alle Seitentypen.

| Datenzeilen | Original-GFM in Chrome | Joplin-GFM in Chrome |
| --- | ---: | ---: |
| 100 | 3,3 ms | 3,6 ms |
| 1.000 | 26,9 ms | 37,8 ms |
| 5.000 | 194,5 ms | 299,7 ms |

Für diese Tabellen sind beide Varianten im Browser grundsätzlich brauchbar. Das deutlich schlechtere Ergebnis des veröffentlichten Joplin-Plugins unter Node darf nicht auf die Browser-Ausführung übertragen werden.

Unter Node benötigte das ursprüngliche Plugin bei 1.000 Zeilen im einzelnen Messdurchlauf rund 17 ms, der Joplin-Fork rund 3,1 Sekunden mit dem Turndown-Kern beziehungsweise 4,6 Sekunden mit dem vollständigen Joplin-Konverter. Dafür gibt es einen passenden bestätigten Fehlerbericht: Wiederholtes Lesen von `table.rows` ist unter Domino teuer. Die Korrektur wurde am 23. Oktober 2026 gemergt, war im geprüften veröffentlichten Paket aber noch nicht enthalten. Quellen: [Fehlerbericht #16894](https://github.com/laurent22/joplin/issues/16894), [Korrektur #16901](https://github.com/laurent22/joplin/pull/16901).

## Aufwand, den uns keine der Varianten abnimmt

1. Sichtbarkeit und Formularinhalte nach unseren Regeln behandeln.
2. Slots, offene und geschlossene Shadow Roots sowie mehrere Frame-Dokumente erfassen.
3. Dokumentwechsel, fehlerhafte Frames und Vollständigkeit korrekt melden.
4. Links absolut auflösen und unsere erlaubten URL-Protokolle beibehalten.
5. Große Ergebnisse automatisch speichern und mit `read_file` zugänglich machen.
6. Komplexe Tabellen semantisch korrekt darstellen oder einen ausdrücklich definierten Fallback verwenden.

Turndown arbeitet synchron, klont übergebene DOM-Knoten und liefert einen vollständigen String zurück. Es stellt keine Streaming- oder Dateiauslagerungs-Schnittstelle bereit. Für unseren gewünschten Aufruf ohne Extraktions-Zeichenlimit löst die Bibliothek daher weder die Erfassung noch die Speicherarchitektur. Eine Verarbeitung in Abschnitten wäre zusätzlich zu entwerfen. Quellen: [RootNode](https://github.com/mixmark-io/turndown/blob/v7.2.4/src/root-node.js), [Konvertierung](https://github.com/mixmark-io/turndown/blob/v7.2.4/src/turndown.js).

## Konkrete Empfehlung für Browserrig

Zunächst im bestehenden Renderer folgende Punkte bearbeiten:

- Wortabstände an Inline-Grenzen erhalten und Markdown-Syntax in normalem Text korrekt escapen.
- Codeblöcke innerhalb von Listen und Zitaten strukturell korrekt ausgeben.
- Tabellen mit `rowspan` und `colspan` auf ein gemeinsames Raster abbilden; für verschachtelte Tabellen einen expliziten Fallback festlegen.
- Die automatische Dateiauslagerung unabhängig vom Antwortbudget umsetzen.
- Die reproduzierten Fälle als gezielte Regressionstests übernehmen.

Durchgestrichenen Text kann eine kleine zusätzliche Regel erhalten. Checkbox-Zustände sollten nur aufgenommen werden, wenn das zum gewünschten Umgang mit Formularinhalten passt.

Falls der Markdown-Umfang später deutlich wächst oder sich die Fehlerbehebung an Inline-Regeln und Verschachtelung wiederholt, wäre **Turndown 7.2.4 als isolierter Formatierer mit eigenen Tabellenregeln** die sinnvollere externe Variante. Das ursprüngliche GFM-Plugin würde ich auch dann nicht einsetzen. Eine solche Integration sollte an den bestehenden Browser-Verträgen gemessen werden und keine Live-DOM-Referenzen ersetzen.

## Ergebnis der Evaluation

Der Turndown-Kern ist stabil genug, um als technische Option erhalten zu bleiben. Der sofortige Nutzen der kompletten Paketlösung ist für Browserrig jedoch begrenzt: Sie beseitigt einige unserer Renderer-Fehler, braucht dafür einen neuen Adapter und lässt die wichtigsten browserbezogenen Aufgaben sowie Teile der Tabellenbehandlung offen. Für den aktuellen Umfang ist die gezielte Weiterentwicklung des vorhandenen Renderers die besser passende Entscheidung.
