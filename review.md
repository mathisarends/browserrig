# Offene Punkte aus dem Code-Review

Die erledigten Abschnitte werden mit den jeweiligen Änderungen entfernt.

## Recording (ursprünglich 3.2.9, 4 und 6.12)

- Segmentverlust durch Tab-Schließung oder Größenlimit darf spätere Segmente nicht verhindern.
- Geschlossene Tabs freigeben, ohne ihre tote CDP-Session zu verwenden.
- `.partial`-Dateien zuverlässig entfernen und Segmentverlust als Event melden.
- `required=True` soll einen Startfehler erzwingen, einen Segmentverlust aber verkraften.
- Fehlermeldungen erhalten, `_disk` typisieren und den Digest nur einmal berechnen.

## Verbleibende Bereinigung und Absicherung (ursprünglich 3.2.10, 4, 6.13 und 8)

- Nudge-Zustand pro Tab als Dataclass bündeln.
- TerminalEvents: Ausschluss von Formularwerten klären und absichern.
- Direkten Browser-Smoke-Test im Chrome-CI-Job ausführen.
- Abschließend alle Lint-, Format-, Typ-, Unit-, Chrome- und Build-Prüfungen ausführen.
