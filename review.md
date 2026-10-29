# Offene Punkte aus dem Code-Review

Die erledigten Abschnitte werden mit den jeweiligen ?nderungen entfernt.

## JavaScript (urspr?nglich 2.2, 2.3, 6.7, 7 und 8.3)

- Alle Skripte einschlie?lich bisheriger Inline-Snippets nach `browserrig/scripts/` verschieben.
- Ein Loader `Script.load`, ein Ausf?hrungsweg `Frame.run`/`run_on_owner`, ein Options-Objekt je Aufruf.
- Gemeinsame Fehlercodes pr?fen; Owner-Aufrufe und Seeding pr?fen Ergebnisse auf dieselbe Weise.
- Scrollen im Owner-Modus vom Element-Modus trennen; keine magischen Positionsargumente.
- Gemeinsame Helfer f?r Geometrie, komponierten DOM, Sichtbarkeit, Hit-Tests und Element-Aufl?sung.
- Sichtbarkeit mit `checkVisibility` und `inert` behandeln, inklusive sichtbarer Kinder versteckter Vorfahren.
- Snapshot-Styles pro Lauf cachen; `element.js` soll keine Snapshot-Closure ben?tigen.
- Globalen Zustand unter `globalThis.__browserrig` und den MutationObserver-Lebenszyklus dokumentieren.
- Markdown bei K?rzung mit geschlossenen Code-Fences zur?ckgeben.
- Seeding-Ablauf und Clip-Payloads zusammenf?hren; Argumente und Ergebnisse typisieren.
- Contract-Tests f?r Dateiform, Inline-JS und Fehlercodes; unbekannte Skripte im Fake ablehnen.

## Caches (urspr?nglich 3.3, 6.8, 6.9)

- Isolated Worlds pro Session/Frame/Dokument cachen und bei Context-Verlust invalidieren.
- Ung?ltigen Context einmal neu anlegen und den Script-Aufruf wiederholen.
- Frame-Discovery pro Aktion/Dokument wiederverwenden; nach Scrollen/Navigation Geometrie erneuern.

## Recording (urspr?nglich 3.2.9, 4 und 6.12)

- Segmentverlust durch Tab-Schlie?ung oder Gr??enlimit darf sp?tere Segmente nicht verhindern.
- Geschlossene Tabs freigeben, ohne ihre tote CDP-Session zu verwenden.
- `.partial`-Dateien zuverl?ssig entfernen und Segmentverlust als Event melden.
- `required=True` soll einen Startfehler erzwingen, einen Segmentverlust aber verkraften.
- Fehlermeldungen erhalten, `_disk` typisieren und den Digest nur einmal berechnen.

## Verbleibende Bereinigung und Absicherung (urspr?nglich 3.2.10, 4, 6.13 und 8)

- Nudge-Zustand pro Tab als Dataclass b?ndeln.
- TerminalEvents: Ausschluss von Formularwerten kl?ren und absichern.
- Direkten Browser-Smoke-Test im Chrome-CI-Job ausf?hren.
- Abschlie?end alle Lint-, Format-, Typ-, Unit-, Chrome- und Build-Pr?fungen ausf?hren.
