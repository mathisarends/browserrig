# Offene Punkte aus dem Code-Review

Die erledigten Abschnitte werden mit den jeweiligen ?nderungen entfernt.

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
