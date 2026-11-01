# smelt-Erkenntnisse aus dem browserrig-Review

Hier steht nur Neues gegenüber der bisherigen `SMELT_FEEDBACK.md`, die upstream
bearbeitet wird. Geprüft mit smelt 0.2.0 auf browserrig `87404ae`. Die Verweise
`F1` … `F15` werden stammen aus dem Review.

Die Funde im Code sind seitdem behoben (Commits `fbca6a8` … `e35c94a`). Die Beispiele
zeigen den Stand von `87404ae`; zum Nachstellen dort auschecken.

## Bug

### F1: SMT313 übersieht Helfer mit Union-Annotation unter Python < 3.14

`files/documents.py`: `_html_text` steht vor `read_html`, smelt meldet nichts (nicht im
Debt, nicht unterdrückt). Der Auslöser ist die Annotation `str | bytes`.

Minimales Repro mit `rules: {public-definitions-first: error}`:

```python
def _h(s: str | bytes):
    return s


def read(p):
    return _h(p)
```

| `python_version` | Annotation von `_h` | SMT313 |
| --- | --- | --- |
| 3.12 | keine, `s: str`, `s: int`, `-> str` | gemeldet |
| 3.12 | `s: str \| bytes` | **nicht gemeldet** |
| 3.14 | `s: str \| bytes` | gemeldet |

Vermutung: Der `|`-Ausdruck einer eager ausgewerteten Annotation gilt als „unknown
execution“ und pinnt die Definition. Bei Builtins und bekannten Klassen ist `|` aber
sicher. Die Fix-Felder sind leer (`fix_blocker: None`), der Grund für das Pinnen ist
also nirgends sichtbar.

Erwartet: gemeldet, wenn beide Operanden Builtins, Importe oder vorher definierte
Klassen sind. Wenn smelt bewusst pinnt, sollte es das wenigstens als Hinweis sagen.

## Lücken in bestehenden Regeln

### F2: Visibility-Regeln prüfen keine Modulkonstanten und Typ-Aliase

`secrets/models.py`: `MIN_LENGTH` und `type SecretValue = ...` werden nur im eigenen
Modul benutzt und nicht exportiert, smelt meldet nichts. SMT316/317/429 decken
Funktionen und Member ab. Die alte Feedback-Datei nannte schon Klassen (`TimeRange`),
Konstanten und `type`-Aliase sind ein weiterer Fall.

Feinheit: `SecretValue` ist der Typ des öffentlichen Feldes `Secret.value`. Ein Alias
in einer öffentlichen Signatur, der nicht exportiert ist, wäre ein eigener Hinweis
(„exportieren oder privat machen“).

### F7: SMT311 könnte `Self` vorschlagen

In `secrets/models.py` ist `OriginPattern.parse(...) -> OriginPattern` der einzige
Grund für `from __future__ import annotations`. Bei reinen Selbstreferenzen in Methoden
wäre der Hinweis „`-> Self` statt Future-Import“ direkt umsetzbar.

Spannungsfeld zu SMT313: Public-first erzeugt Vorwärtsreferenzen (`capture()` vor
`CaptureStrategy`, `Keyboard` vor `_Stroke`, `Nudges` vor `_TabState`), die unter
3.12 den Future-Import verlangen. browserrig hat das entschieden: Der Import ist dann
in Ordnung (3.12 bis 3.14 werden unterstützt), Quoten einzelner Annotationen ist nicht
gewollt. Ein Satz dazu in `explain SMT311`/`SMT313` wäre hilfreich, damit Agents nicht
zwischen den beiden Regeln pendeln: „Braucht public-first eine Vorwärtsreferenz, ist
der Future-Import der vorgesehene Weg.“

## Kandidaten für neue Regeln

Jeweils mit Fund in browserrig. Gemessen an der Scope-Bremse aus `docs/vision.md`: Die
ersten vier sind deterministisch und haben wenig Fehlalarm-Risiko.

### F4: String-Literal entspricht einem vorhandenen `StrEnum`-Wert

```python
# files/containers.py:108
elif format_ in {"eml", "mbox"}:          # FileExtension.EML, FileExtension.MBOX existieren
elif format_ in {"gz", "bz2", "xz"}:
```

Erkennung: Vergleich oder `in`-Menge, in der alle Literale Werte genau eines
Projekt-`StrEnum` sind. Vorschlag: die Members benutzen. Das Risiko ist gering, wenn die
Menge mindestens zwei Literale hat oder die Variable aus dem Enum stammt.

### F3: Doppelte Konstante

`observation/render.py:17` `_CHECKABLE` ist inhaltlich gleich
`observation/extraction/semantics.py:33` `CHECKABLE_ROLES`. Erkennung: gleiche
`frozenset`/`tuple`-Literale (Länge ≥ 3) in mehreren Modulen. Vorschlag: aus einer
Stelle importieren.

### F5: Optionaler Parameter als Positionsparameter

```python
# browser/downloads.py
def __init__(self, files: FileSystem | None, directory: str | None, emit: EventSink): ...
# browser/chrome.py:93
Downloads(self.files, self._options.download_directory, self.events.emit)
```

Erkennung: Ein Parameter mit `X | None` oder ein zweiter Parameter gleichen Typs ist
nicht keyword-only. pylints `too-many-positional-arguments` deckt nur die Anzahl ab
(und ist hier ausgeschaltet). Der Typ-Aspekt ist neu.

### F6: `getattr`/`hasattr` mit Literal-Namen auf bekannt typisierten Werten

```python
# terminal.py, event: _TerminalEvent (type-Union)
call = getattr(event, "call", None)
if result is not None and hasattr(result, "is_error"): ...
```

Erkennung: `getattr(x, "lit", ...)`/`hasattr(x, "lit")`, wenn `x` annotiert ist
(Klasse oder Union von Klassen). Vorschlag: `match`/`isinstance`. Ruff B009 deckt nur
`getattr` ohne Default ab.

Zweiter Fund, als Typprüfung über ein Attribut getarnt:

```python
# secrets/models.py; Totp hat ein Klassenattribut `rotating = True`
return bool(getattr(self.value, "rotating", False))   # gemeint: isinstance(self.value, Totp)
```

### F9: Durchreich-Factory

```python
def totp(seed, *, digits=6, period=30, digest="sha1") -> Totp:
    return Totp(seed, digits=digits, period=period, digest=digest)
```

Erkennung: Der Funktionsrumpf ist nur `return Klasse(...)` mit allen Parametern 1:1.
Ausnahme: ein Docstring- oder Decorator-Vertrag, den die Klasse nicht hat.

### F10: Mehrere öffentliche Hauptklassen in einem großen Modul (Policy)

`browser/tab.py`: `Frame` und `Tab` auf 675 Zeilen. Als Opt-in-Policy mit Ausnahmen
für Sammelmodule (`models`, `config`, `kinds`, `events`) und einer Zeilenschwelle.

### F11: Platzierung mutabler Zustands-Dataclasses (Policy)

Fünf Plugins definieren eine `_State`-Dataclass in der Plugin-Datei. Der Wunsch ist
eine eigene Datei pro Paket. Als Contract etwa „nicht-frozen Dataclasses nur in
`state`/`models`“. Projektspezifisch, deshalb höchstens eine Policy.

### F8: Primitive ID-Keys (Hinweis, niedrige Priorität)

`dict[str, _TabState]`, dessen Keys aus `event.target_id` kommen. Erkennbar wäre: ein
Container-Feld mit `str`-Key, das nur mit `*.xxx_id` befüllt wird. Wahrscheinlich zu
heuristisch, eher Urteil.

### F12: Methodenaufruf auf mehrzeiligem Konstruktor (niedrige Priorität)

`PageFingerprint(...20 Zeilen...).digest()`. Deterministisch erkennbar, aber reiner
Stil.

### F14: Lambda, das Parameter verwirft, um eine Signatur anzugleichen

```python
# files/adapters.py
def document(reader: Callable[[Path], ParsedContent]) -> Reader:
    return lambda path, _request, _options: reader(path)

def container(format_: str) -> Reader:
    return lambda path, _request, options: containers.container_index(
        path, format_, options.max_expanded_bytes
    )
```

Erkennung: Eine Funktion gibt nur ein `lambda` zurück, dessen Parameter mit `_`
beginnen oder im Rumpf nicht vorkommen, und mehrere solcher Funktionen stehen im
selben Modul. Vorschlag: den Zielen eine gemeinsame Signatur oder ein Kontextobjekt
geben. Eher Hinweis als Fehler, weil einzelne Adapter legitim sein können.

### F15: Zuweisung, die nur ein `assert` liest

```python
# tools/mouse.py, click_at und drag_at
snapshot = self._observe.snapshot
assert snapshot is not None
# snapshot wird danach nicht mehr benutzt
```

Erkennung: Eine lokale Variable wird zugewiesen, und der einzige Lesezugriff ist ein
`assert`. Ruff F841 sieht den Lesezugriff im `assert` und meldet nichts. Unter `-O`
fällt der Lesezugriff ganz weg. Vorschlag: Zuweisung und `assert` entfernen, oder
die Prüfung als echte Bedingung schreiben, wenn sie ein Vertrag ist.

### F16: Öffentliche Kompatibilitätsklasse ohne Nutzer (Hinweis)

```python
# tools/mouse.py
class MouseTools(PointerTools, DomPointerTools):
    """Compatibility group. New recipes mount PointerTools and DomTools explicitly."""
```

Die Klasse hat keinen Rumpf, erbt nur, und weder Paket noch Tests oder Beispiele
benutzen sie. Erkennung: eine Klasse ohne eigene Member, deren Basen alle aus dem
Projekt stammen, und ohne Referenz im Projekt. Für Libraries nur als Hinweis, weil
externe Nutzer unsichtbar sind.

## Fund ohne Regel-Vorschlag

Toter Zweig über Modulgrenzen: `files/containers.py` `container_index` hatte einen
`elif format_ == "eml"`-Zweig. `FORMATS` leitet `eml` aber an `documents.read_email`
weiter, nie an den Container-Reader. Erkennbar wäre das nur mit Datenfluss über die
Dispatch-Tabelle, für smelt zu viel. Eher ein Argument für Typen statt `str`
(`format_: FileExtension`).

## Architektur-Tests, die smelt ersetzen könnte

### F13

`tests/test_architecture.py` prüft Paketgrenzen per Hand mit `ast.walk` (dreimal fast
derselbe Code):

- `core` importiert nichts aus `browserrig.*` außer `core`. Das ist mit Layern
  (SMT101) ausdrückbar.
- `input`/`files` nicht → `browser`, `readiness` nicht → `observation`, `scripts`
  nicht → `browser`/`observation`/`readiness`. Ebenfalls SMT101/SMT102.
- `tools` importiert kein `cdpify`. Das deckt SMT103 ab.
- `tools` greift auf kein Attribut `.cdp` zu. **Damit ist das in smelt nicht
  ausdrückbar.** Kandidat: ein Contract „verbotene Attribute/Member pro Paket“.

Nächster Schritt in browserrig: die ersten drei Punkte als `architecture` in
`smelt.yml` übernehmen und den Test auf den `.cdp`-Fall verkleinern. Damit verschwindet
auch das Banner „Policy coverage: incomplete“.
