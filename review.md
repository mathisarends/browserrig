# Code-Review browserrig

Stand: Commit `a01b2e2` plus die gestagten Änderungen. Geprüft habe ich alle Python-Module unter `browserrig/`, alle JS-Skripte, die Tests und die Beispiele.


## TL;DR

- **Insgesamt sauber.** Die Plugin-Aufteilung ist klar (Activity, Chrome, Readiness, Nudges, Observe, Actions, Recording), die Optionen sind streng typisiert (`frozen`, `extra=forbid`), die Fehler sind modellfreundlich formuliert und die Readiness- und Capture-Strategien sind gut austauschbar.
- **Law of Demeter:** Die 4er- und 5er-Ketten haben fast alle zwei Ursachen.
  1. Die Tools greifen durch `Actions` hindurch auf `Browser`, `Observe` und `Tab.input` zu.

  `tab.cdp.page.navigate(...)` selbst ist dagegen CDP-Namespacing (Domain.Methode) und für mich in Ordnung.
- **Konkrete Umbauvorschläge mit Vorher/Nachher-Code** stehen in Abschnitt 6.
- **JavaScript (Abschnitt 7):** Es gibt fünf verschiedene Wege, JS auszuführen, und sieben JS-Snippets, die als Strings im Python-Code stehen und weder von ESLint noch von Prettier geprüft werden. Mein Vorschlag: Alles JS liegt in `.js`-Dateien, es gibt genau einen Loader (`Script`) und genau einen Ausführungsweg (`frame.run(script, args)`), und gemeinsame Helfer stehen in `lib/`.
- **Tests und Beispiele (Abschnitt 8):** Die Integrationstests mit echtem Chrome sind stark. Für Bug 2 und die Races aus 3.2 fehlen noch Tests, und Contract-Tests würden die JS-Konvention absichern.

---

## 1. Law of Demeter / Punktketten

Die Ketten habe ich per AST-Scan gefunden. Tiefe = Anzahl der Punkte im Ausdruck.

### 1.1 Tiefe ≥ 4

| Stelle | Ausdruck | Bewertung |
|---|---|---|
| `tools/navigation.py:85` | `actions.browser.active_tab.input.emit(WaitingEvent(...))` | **Schlechteste Stelle.** Ein Tool geht durch vier Objekte, nur um ein Event zu senden |
| `browser/frames.py:37,68` | `(await x.cdp.page.get_frame_tree()).frame_tree` | Ergebnis-Unwrapping, siehe Vorschlag `Tab.frame_tree()` |
| `browser/chrome.py:268` | `(await ...target.get_targets()).target_infos` | ok, aber in einen Helper auslagern |
| `observation/content.py:25` | `.replace(...).replace(...)...` | Fluent-Stil auf `str`, **kein Problem** |

### 1.2 Auffällige Tiefe 3 (zeigt das Muster)

- `tools/files.py`: `self.actions.browser.downloads / .files / .open_file`
- in allen Tools: `actions.observe.snapshot(...)`, `actions.observe.element(...)`
- `tools/tabs.py`: `actions.browser.tabs() / open_tab / activate_tab / close_tab`
- `browser/plugin.py:30`: `browser.active_tab.mouse.publish_cursor(...)`
- `tools/dialogs.py`: `self.browser.active_tab.dialog`
- Tools rufen CDP direkt auf: `tab.cdp.page.navigate_to_history_entry`, `get_navigation_history`, `reload`, `handle_java_script_dialog`, `bring_to_front`
- `browser/tab.py:181-183`: `tree.frame_tree.frame.url / .loader_id / .id`
- `browser/tab.py` (visible_points): `current.parent.projection.inverse`
- `recording/plugin.py:93,130,136,186`: `tab.cdp.page.start_screen_recording`, `tab.cdp.io.read/close`

### 1.3 Ursache

`Actions` ist im Moment ein **Service-Locator**: Die Tools bekommen `actions` und holen sich daraus `browser`, `observe`, `browser.active_tab` und so weiter. Dadurch kennt jedes Tool die interne Struktur von drei bis vier Klassen. Und weil die Tools direkt mit CDP sprechen, ist `Tab` keine echte Abstraktion. Eine CDP-Änderung schlägt bis in die Tool-Schicht durch.

### 1.4 Verbleibende Vorschl?ge

- Tab-Methoden kapseln CDP-Navigation, Dialoge und Uploads (6.4).
- Tools injizieren Browser/Observe direkt (6.5).
- Browser.publish_cursor kapselt den aktuellen Tab.
- Frame-Trees werden in einem Helper entpackt.

---

## 2. Organisation und Schnittstellen

### 2.2 Skripte und Script-Loading

- `ELEMENT_SCRIPT` ist in `observation/capture.py` definiert, wird aber nur in den Tools benutzt (`tools/execution.py`, `tools/scrolling.py`).
- `SCROLL_SCRIPT` liegt als Datei in `observation/scripts/`, wird aber in `tools/scrolling.py` geladen.
- Das Muster `files(...).joinpath("scripts/x.js").read_text(encoding="utf-8")` steht sechsmal im Code.
- `script_call` liegt in `browser/tab.py:219`, wird aber nur von `readiness/canvas.py` benutzt.

Die ausführliche Analyse und der Vorschlag für eine einheitliche Abstraktion stehen in **Abschnitt 7**.

### 2.3 Duplikate

- **Seeding-Logik doppelt:** `observation/content.py::_seed` (Zeilen 53-68) und `DomCapture._extract` (`observation/capture.py:74-87`) enthalten denselben Ablauf: `__browserrigDOM` zurücksetzen, `capture_snapshot` pro Session cachen, `seed_dom` aufrufen und Limitations eintragen. Der Ablauf gehört als `seed_frame(frame, metadata, limitations)` neben `seed_dom` in `observation/dom.py`.
- `frame.local_clip.model_dump() if frame.local_clip else None` steht viermal im Code (`capture.py:94`, `execution.py:184`, `scrolling.py:42,48`). Eine Property `Frame.clip_payload` oder ein Helper würde reichen.
- `Projection.box` und `Projection.local_box` sind fast identisch. Eine gemeinsame private Methode mit Parameter wäre besser.
- `PageView` und `ElementView.from_element` kopieren Feld für Feld aus `Element`. Mit `model_validate(element, from_attributes=True)` oder einer gemeinsamen Basis wäre das kürzer.
- `Tab.press_key` (`tab.py:193`) delegiert nur an `keyboard`. Das ist überflüssige API-Fläche: Entweder wird `tab.keyboard` benutzt oder ausschließlich `press_key`, aber nicht beides.

### 2.4 Öffentliche API (`__init__.py`)

- `browserrig/__init__.py` importiert teils aus Untermodulen (`.observation.plugin`, `.readiness.config`) statt aus den Paketen. Das sollte einheitlich über die Paket-`__init__` laufen.
- `readiness/__init__` exportiert `kinds` erneut, `input/__init__` exportiert `MouseEventKind` erneut. Kinds und Events liegen aber global in `kinds.py` und `events.py`. Hier sollte man sich auf einen Ort festlegen.
- `ActionFinishedEvent` trägt viele `before_*`-Felder. Ein verschachteltes `before: PageState` wäre lesbarer und spart die Feldpaare.

### 2.6 Kleinere Schnittstellenfragen

- `InteractionTools(PointerTools)`: Dadurch erbt der DOM-Modus auch `click_at` (Koordinaten-Klick). Falls das gewollt ist, sollte es in einem Kommentar stehen. Falls nicht, wäre Komposition besser als Vererbung.
- `Tab.main_frame()` (`tab.py:179`) ist ein Getter mit Seiteneffekt: Er überschreibt `document_id` und `url`. Er wird sehr oft aufgerufen und konkurriert mit dem Listener in `chrome.py`, der dieselben Felder setzt. Besser wäre: `main_frame()` liest nur, und nur der Listener schreibt (oder ein explizites `refresh()`).

---

## 3. Bugs

### 3.2 Plausibel (Races und Randfälle)

4. **Bei offenem Dialog kann man den Tab nicht wechseln.** `switch_tab` und `open_tab` laufen über `Actions._prepare`, und das wartet auf Readiness des *aktuellen* Tabs. Hat der aktuelle Tab einen offenen Dialog, ist das Ergebnis `BLOCKED`, und man kommt nicht mehr weg. Tab-Management sollte die Readiness des alten Tabs überspringen.
5. **`handle_dialog` und `wait` laufen ohne `action_lock`** (`tools/dialogs.py`, `tools/navigation.py`). Sie können also parallel zu einer laufenden Aktion arbeiten. Bei `handle_dialog` ist das vermutlich gewollt (der Dialog blockiert ja die Aktion), dann aber bitte mit Kommentar. Bei `wait` eher nicht.
6. **Inkonsistente `document_id` in `wait_for_page`.** `ReadinessStartedEvent` trägt die `document_id` vom Start, der Report die vom Ende. Nach einer Navigation passen Start- und End-Event nicht zusammen.
9. **Recording ist nach einer Tab-Schließung tot.** Wird der aufgenommene Tab geschlossen, ruft `_stop` `stop_screen_recording` auf einer toten Session auf. Das schlägt fehl, `_failed` setzt `state.failed = True`, und `ensure_started` startet danach für die ganze Session nie wieder (`recording/plugin.py:81`). Mit `required=True` gibt es zusätzlich eine `RecordingError`. Hier sollte zwischen „Segment verloren“ und „Recording kaputt“ unterschieden werden. Dasselbe gilt für das Überschreiten von `max_bytes`: Die `.partial`-Datei bleibt außerdem liegen.
10. **`terminal.py::_event_record`** entfernt nur die Felder `text` und `message`. Falls dort sensible Inhalte (Formularwerte, URLs mit Tokens) gefiltert werden sollen, fehlt z. B. `value`. Falls es nur um die Länge geht, ist es ok.

### 3.3 Performance

- **`create_isolated_world` bei jedem Aufruf.** Jedes `Frame.evaluate/call` (`tab.py:103`) erzeugt zuerst eine Isolated World, das ist ein zusätzlicher Roundtrip pro Aufruf. `Tab.evaluate` kostet so drei Roundtrips. Die Context-ID sollte pro `(frame_id, loader_id)` gecacht werden.
- **Frame-Discovery mehrfach pro Aktion.** `element_point` ruft `observe.element` auf, und das läuft 2–3-mal `browser.frames()` (volle Frame-Discovery). `drag` ruft `element_point` viermal auf. `prepare_element` macht die Frame-Discovery in jeder Schleifeniteration. Ein Frame-Cache pro Aktion (an `document_id` gebunden) würde viele CDP-Calls sparen.

---

## 4. Stil

- `validated_url` mischt `or` und `and` ohne Klammern. Das ist korrekt, aber schwer zu lesen. Klammern setzen oder in benannte Bedingungen aufteilen.
- `keyboard.py`: `_Stroke("", (modifier,)).flags` ist ein Umweg für `_MODIFIERS[modifier]`.
- `scrolling._plan`: `child.owner_call(SCROLL_SCRIPT, False, 0, clip, local)` nutzt magische Positionsargumente. Ein Dict bzw. benannte Argumente (wie bei `script_call`) wären besser.
- Fehlermeldungen in `recording/plugin.py:112,181` geben nur `type(error).__name__` aus. Das ist dasselbe Muster wie Bug 1, nur unkritischer. Für Diagnose wäre `f"{type(error).__name__}: {error}"` hilfreicher.
- `recording/plugin.py:218`: `_disk(function, *arguments)` ist untypisiert. `Callable[P, R]` mit `ParamSpec` würde reichen.
- `recording/plugin.py:164,173`: `digest.hexdigest()` wird zweimal berechnet. Einmal in eine Variable.
- `Nudges` hält viel Zustand in losen Dicts. Ein kleines Dataclass pro Tab bzw. Dokument wäre übersichtlicher.
- `# pylint: disable=broad-exception-caught` steht oft mit gutem Kommentar dabei. 👍 Bei `BaseException` (siehe Bug 2) stimmt der Kommentar aber nicht mehr.
- Die Benennung ist sehr konsistent. Die Module sind klein und gut fokussiert.

---

## 5. Priorisierte Maßnahmen

| Prio | Maßnahme | Aufwand |
|---|---|---|
| 🟡 8 | Demeter: Tab-Methoden (`go_back`, `reload`, `handle_dialog`, …); Tools sprechen kein CDP mehr | mittel |
| 🟡 9 | Demeter: Tools injizieren `Browser`/`Observe` direkt statt über `actions.` | mittel |
| 🟢 11 | `scripts/`-Modul mit `load_script`; Seeding-Duplikat und `clip_payload` zusammenführen | klein |
| 🟢 12 | Isolated-World- und Frame-Cache (Performance) | mittel |
| 🟢 13 | Verbleibende Stilpunkte aus Abschnitt 4 | klein |
| 🟠 14 | JS: alles in `.js`-Dateien, ein `Script`-Loader, ein Ausführungsweg (Abschnitt 7.4, Schritte 1–3) | mittel |
| 🟡 15 | JS: gemeinsame Helfer in `lib/`, Sichtbarkeit über `checkVisibility()` (7.3, 7.4 Schritt 4) | mittel |
| 🟡 16 | Tests für die Bugs aus Abschnitt 3 sowie Contract-Tests für Skripte und Fehlercodes (Abschnitt 8) | klein |
| 🟢 17 | Typisierte Skripte (`Script[Args, Result]`, 7.4 Schritt 5) | mittel |

---

## 6. Umbauvorschläge im Detail (Vorher/Nachher)

Die Skizzen zeigen die Richtung. Sie sind bewusst knapp gehalten und nicht 1:1 lauffähig.

### 6.4 Tab kapselt CDP für die Tools

**Vorher** (verteilt über `tools/navigation.py`, `tools/dialogs.py`, `tools/tabs.py`):
```python
history = await tab.cdp.page.get_navigation_history()
entry = history.entries[history.current_index - 1]
await tab.cdp.page.navigate_to_history_entry(entry_id=entry.id)
...
await tab.cdp.page.handle_java_script_dialog(accept=accept, prompt_text=text)
```

**Nachher:**
```python
class Tab:
    async def go_back(self) -> bool: ...
    async def go_forward(self) -> bool: ...
    async def reload(self) -> None: ...
    async def handle_dialog(self, *, accept: bool, text: str | None = None) -> None: ...
    async def bring_to_front(self) -> None: ...
    async def frame_tree(self) -> FrameTree: ...

# Tool
async def back(tab: Tab) -> Effect:
    if not await tab.go_back():
        raise BrowserError("No earlier history entry")
    return Effect("Navigated back.")
```

Regel für die Zukunft: **Keine Datei unter `tools/` importiert `cdpify`.** Das lässt sich automatisch absichern, z. B. mit `import-linter`:

```toml
[[tool.importlinter.contracts]]
name = "tools do not talk CDP"
type = "forbidden"
source_modules = ["browserrig.tools"]
forbidden_modules = ["cdpify"]
```

### 6.5 Tools injizieren direkt statt `actions.browser.…`

**Vorher** (`tools/navigation.py:85`):
```python
async def wait(self, seconds: float = 1, *, actions: Inject[Actions]) -> str:
    await actions.browser.active_tab.input.emit(WaitingEvent(duration=seconds))
```

**Nachher:**
```python
async def wait(self, seconds: float = 1, *, browser: Inject[Browser]) -> str:
    await browser.emit(WaitingEvent(duration=seconds))
```

Analog in `tabs.py`, `files.py` und `dialogs.py`: `browser: Inject[Browser]` bzw. `observe: Inject[Observe]` als eigene Parameter. `Actions` ist dann nur noch das, was der Name sagt, nämlich der Ausführungsrahmen für Aktionen (`run`, `element_call`, `element_point`), und kein Service-Locator mehr.

### 6.7 Script-Loading

```python
# browserrig/scripts/__init__.py
from functools import cache
from importlib.resources import files

@cache
def load_script(name: str) -> str:
    return files(__package__).joinpath(f"{name}.js").read_text(encoding="utf-8")

SNAPSHOT = load_script("snapshot")
ELEMENT = load_script("element")
SCROLL = load_script("scroll")
```

Damit die Zyklen nicht wiederkommen, kommt ein Layer-Vertrag dazu (ebenfalls `import-linter`):

```toml
[[tool.importlinter.contracts]]
name = "layers"
type = "layers"
layers = [
  "browserrig.tools",
  "browserrig.observation | browserrig.readiness | browserrig.recording | browserrig.nudges",
  "browserrig.browser",
  "browserrig.input | browserrig.files",
  "browserrig.core | browserrig.scripts",
]
```

Die genaue Schichtung von observation und readiness muss man noch festlegen. Wenn Readiness Observation braucht, stehen die beiden in zwei getrennten Schichten statt nebeneinander.

### 6.8 Isolated World pro Dokument cachen (Performance)

**Vorher** (`browser/tab.py:102-106`): Jedes `evaluate`/`call` ruft vorher `create_isolated_world` auf.

**Nachher:**
```python
class Frame:
    _context_id: int | None = None

    async def context(self) -> int:
        if self._context_id is None:
            result = await self.cdp.page.create_isolated_world(
                frame_id=self.id, world_name="browserrig"
            )
            self._context_id = result.execution_context_id
        return self._context_id
```

Weil `Frame`-Objekte heute pro Discovery neu entstehen, muss der Cache an einer Stelle liegen, die länger lebt, z. B. im Tab als Dict `{(frame_id, loader_id): context_id}`. Verworfen wird er bei `Runtime.executionContextsCleared` bzw. `executionContextDestroyed`. Beim Fehler „Cannot find context with specified id“ wird die World einmal neu erzeugt und der Aufruf wiederholt. Das spart pro Script-Aufruf einen Roundtrip.

### 6.9 Frames pro Aktion nur einmal entdecken

Ein kleiner Cache, der an Dokument und Aktion gebunden ist, reicht:

```python
async def frames(self, tab: Tab) -> tuple[Frame, ...]:
    key = (tab.id, tab.document_id, tab.input.action_id)
    if not key[2] or self._frames_key != key:      # outside an action: always fresh
        self._frames, self._frames_key = await self.browser.frames(tab), key
    return self._frames
```

Damit laufen `drag` (viermal `element_point`) und `prepare_element` (Schleife) nur einmal durch die Frame-Discovery. Ändert sich das Dokument, ändert sich auch der Key, und der Cache verfällt.

### 6.10 `Tab.main_frame()` ohne Seiteneffekt

**Vorher:** `main_frame()` überschreibt `document_id` und `url` (`tab.py:179-190`).

**Nachher:** Lesen und Schreiben sind getrennt und an den Namen erkennbar:

```python
async def main_frame(self) -> Frame:          # pure query
    tree = await self.frame_tree()
    return Frame(id=tree.frame.id, cdp=self.cdp)

async def sync_document(self) -> None:        # deliberate write
    tree = await self.frame_tree()
    self.document_id, self.url = tree.frame.loader_id, tree.frame.url
```

`Actions._prepare` ruft `sync_document()` auf, alle anderen Stellen `main_frame()`. Im Normalfall pflegt der Listener (`FrameNavigatedEvent`) die Felder.

### 6.12 Recording: Segmentverlust vom Totalausfall trennen

```python
async def _stop(self) -> None:
    ...
    except Exception as error:
        # Lost segment (tab closed, too large): report it, keep recording later tabs.
        await self.browser.emit(
            RecordingSegmentLostEvent(reason=f"{type(error).__name__}: {error}")
        )
        await asyncio.to_thread(partial.unlink, missing_ok=True)
```

`state.failed = True` gibt es dann nur noch, wenn `start_screen_recording` grundsätzlich scheitert. Ein Hook auf `TabClosedEvent` gibt den aufgenommenen Tab frei, ohne `stop_screen_recording` auf einer toten Session aufzurufen. Mit `required=True` schlägt erst ein Startfehler hart fehl, nicht schon ein verlorenes Segment.

### 6.13 Kleinkram mit Code

```python
# keyboard.py
flags = _MODIFIERS[modifier]                     # statt _Stroke("", (modifier,)).flags

# scrolling._plan – benannte Argumente statt magischer Positionen
# (scroll.js müsste dafür ein Options-Objekt annehmen)
await child.owner_call(SCROLL_SCRIPT, {"apply": False, "delta": 0, "clip": clip, "local": local})

# Frame – ein Helper statt vier Kopien
@property
def clip_payload(self) -> dict[str, float] | None:
    return self.local_clip.model_dump() if self.local_clip else None

# recording/plugin.py – typed _disk
async def _disk[**P, R](function: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R: ...
```

`ActionFinishedEvent` mit verschachteltem Vorher-Zustand:

```python
class PageState(Options):
    url: str
    document_id: str
    fingerprint: str
    scroll_y: float

class ActionFinishedEvent(Event):
    action_id: str
    before: PageState
    after_url: str
    ...
```

---

## 7. JavaScript: eine einheitliche Script-Abstraktion

### 7.1 Bestandsaufnahme

**JS-Dateien** (1.040 Zeilen):

| Datei | Form | Argumente | Ausgeführt über |
|---|---|---|---|
| `observation/scripts/snapshot.js` | Funktionsdeklaration | ein Options-Objekt | `frame.call` (`capture.py:88`) |
| `observation/scripts/element.js` | Funktionsdeklaration | 5 Positionsargumente | `frame.call` (`execution.py:198`, `scrolling.py:36`) |
| `observation/scripts/scroll.js` | Funktionsdeklaration | 4 Positionsargumente, `token === false` schaltet in einen zweiten Modus | `frame.call` **und** `owner_call` (`scrolling.py:45,49`) |
| `observation/scripts/content.js` | Funktionsdeklaration | 1 Positionsargument | `frame.call` (`content.py:93`) |
| `readiness/scripts/canvas.js` | Funktionsdeklaration | ein Options-Objekt | `tab.evaluate(script_call(...))`: JSON wird als String in einen Ausdruck eingebaut |
| `readiness/scripts/dom.js` | **IIFE-Ausdruck** `(() => {...})()` | keine | `tab.evaluate` |

**JS als String im Python-Code** (wird weder gelintet noch formatiert):

| Stelle | Inhalt | Ausgeführt über |
|---|---|---|
| `browser/frames.py:18-27` (`_OWNER_SIZE`) | Sichtbarkeit und Innenmaß des iframe-Elements | `owner_call` |
| `browser/frames.py:38` | `"[innerWidth, innerHeight]"` | `evaluate` |
| `browser/tab.py:81-93` | Hit-Test über Shadow-Grenzen (`visible_points`) | `owner_call` |
| `observation/dom.py:10-16` (`_SEED_SCRIPT`) | setzt `__browserrigDOM` | **roher** `cdp.runtime.call_function_on` |
| `observation/capture.py:74`, `observation/content.py:56` | `"globalThis.__browserrigDOM = null"` | `evaluate` |
| `observation/capture.py:221-222` | `PageFacts`-Ausdruck | `evaluate` |

**Fünf Ausführungswege:**
1. `Frame.call`: `callFunctionOn` in der Isolated World, übersetzt die Fehlercodes.
2. `Frame.evaluate` / `Tab.evaluate`: `Runtime.evaluate` mit einem Ausdruck, liefert eine generische Fehlermeldung.
3. `Frame.owner_call`: `callFunctionOn` auf dem iframe-Element im Parent. Er hat eine eigene Fehlermeldung, **übersetzt keine Fehlercodes** und setzt kein `await_promise`.
4. `script_call`: baut aus Funktion und JSON-Argumenten einen Ausdruck für `evaluate`.
5. `observation/dom.py:62`: roher `call_function_on` mit Objekt-Argumenten, **ohne jede Fehlerprüfung**.

### 7.2 Probleme

- **Inline-JS fällt durch das Tooling.** ESLint (`max-depth`, `eqeqeq`, `curly`, …) und Prettier laufen nur über `browserrig/**/*.js`. Die Snippets oben werden nie geprüft. `pyproject.toml` schaltet sogar `line-too-long` ab, mit der Begründung „allowing long embedded HTML/JS strings“.
- **Die Konvention aus `eslint.config.mjs` wird nicht durchgehalten.** Dort steht „CDP receives each file as a standalone function declaration“. `dom.js` ist aber ein IIFE, und `canvas.js` ist zwar eine Funktion, wird aber per `script_call` in einen Ausdruck mit eingebettetem JSON umgebaut.
- **Uneinheitliche Argumente.** `snapshot` und `canvas` bekommen ein Options-Objekt, `element`, `scroll` und `content` Positionsargumente. In `scroll.js` steuert `token === false` einen zweiten Modus („`this` ist das iframe-Element“). Daher kommt das unlesbare `owner_call(_SCROLL_SCRIPT, False, 0, clip, local)`.
- **Uneinheitliche Fehler.** Nur `Frame.call` übersetzt Fehlercodes. Wirft `scroll.js` im Owner-Modus `ELEMENT_BLOCKED` (`scroll.js:192`), macht `owner_call` daraus die generische Meldung „Frame owner could not be inspected“ (`tab.py:65`). Die Codes stehen als Tupel in `tab.py:132-140`, getrennt von den `throw`-Stellen in JS. Heute stimmen beide Seiten überein, aber nichts prüft das.
- **Versteckter globaler Vertrag.** Drei Globals in der Isolated World koppeln die Skripte aneinander, ohne dass das irgendwo beschrieben ist:
  - `__browserrigDOM`: geschrieben von `_SEED_SCRIPT` (`dom.py`), per Inline-String zurückgesetzt in `capture.py` und `content.py`, gelesen von `snapshot.js`, `scroll.js` und `content.js`.
  - `__browserrigElements`: geschrieben von `snapshot.js:405`, **inklusive der Closure `pointFor`**, gelesen von `element.js` (`state.pointFor`, Zeile 73) und `scroll.js`. `element.js` funktioniert also nur, wenn vorher `snapshot.js` in derselben World lief, und benutzt dann dessen Closure.
  - `__browserrigStability`: geschrieben von `dom.js`.

**Doppelte Helfer:**

| Helfer | Vorkommen |
|---|---|
| `intersect` | `snapshot.js:35`, `scroll.js:19` |
| `parentFor` | `snapshot.js:14`, `scroll.js:11` |
| Closed Shadow Roots aus `__browserrigDOM` und Kinder über Shadow/Slot | `snapshot.js:8,326`, `scroll.js:12`, `content.js:2,54` |
| Sichtbarkeit (display/visibility/opacity/inert) | `snapshot.js:49` und `:120`, `frames.py:19` (`_OWNER_SIZE`), `content.js:78` |
| Hit-Test über Shadow-Grenzen | `snapshot.js:75` (`hits`), `tab.py:81` (inline), **mit unterschiedlicher Semantik** (`containsComposed` vs. `hit !== target`) |
| Stale- und Disabled-Prüfung | `element.js:2-9`, `scroll.js:2-9` |

### 7.3 Fehler und Auffälligkeiten in den Skripten

4. **`content.js:250`:** `markdown.slice(0, maxChars)` passiert *nach* dem Einsetzen der Code-Literals. Ein Schnitt kann mitten in einem ```` ``` ````-Fence landen, und der Rest ist dann ein offener Codeblock. Besser vor dem Einsetzen kürzen oder nach dem Kürzen offene Fences schließen.
5. **Performance in `snapshot.js`:** `getComputedStyle` läuft pro Element für jeden Vorfahren, und das mehrfach: in `renderedBounds`, in `visibleBounds` pro Client-Rect und zweimal in `interactive`. Bei tiefen DOMs ist das O(n·Tiefe). Ein Cache `Map<Element, CSSStyleDeclaration>` pro Snapshot-Lauf ist eine kleine Änderung mit großer Wirkung.
6. **`dom.js`** installiert einen `MutationObserver`, der nie getrennt wird. Das ist ok, weil ein Guard dafür sorgt, dass es nur einen pro Dokument gibt. Man sollte es aber dokumentieren.

### 7.4 Vorschlag: eine Script-Abstraktion

**Ziele:**
1. Jedes Stück JS ist eine `.js`-Datei.
2. Es gibt genau einen Loader.
3. Es gibt genau einen Ausführungsweg mit einheitlichen Fehlern.
4. Gemeinsame Helfer werden geteilt statt kopiert.
5. Argumente und Ergebnisse sind typisiert.

**Schritt 1: Verzeichnis und Konvention**

```
browserrig/scripts/
  __init__.py          # Script, ScriptError, Konstanten
  README.md            # Konvention und globaler Zustand
  lib/                 # geteilte Helfer, nur Funktionsdeklarationen
    geometry.js        # intersect, contains
    composed.js        # parentFor, childrenFor, closedRoots
    visibility.js      # isRendered(el) auf Basis von checkVisibility + inert
    hit.js             # hitsComposed(el, x, y)
    elements.js        # resolveElement({token, index}) inkl. STALE/DISABLED
  snapshot.js
  element.js
  scroll.js            # nur noch der Element-Modus
  scroll_owner.js      # der heutige Modus token === false
  content.js
  canvas.js
  stability.js         # heute readiness/scripts/dom.js, als Funktion statt IIFE
  seed.js              # heute _SEED_SCRIPT in observation/dom.py
  reset.js             # heute "globalThis.__browserrigDOM = null"
  page_facts.js        # heute Inline-Ausdruck in capture.py:221
  viewport.js          # heute "[innerWidth, innerHeight]" in frames.py:38
  owner_size.js        # heute _OWNER_SIZE in frames.py
  owner_hits.js        # heute inline in tab.py:81
```

Die Konvention (in `eslint.config.mjs` und `scripts/README.md`):
- Jede Datei außerhalb von `lib/` enthält **genau eine** Funktionsdeklaration `function browserrig<Name>(args)`, deren Name zum Dateinamen passt.
- Es gibt **genau ein** Argument, ein Options-Objekt (`{token, index, clip}`), nie Positionsargumente.
- `this` ist nur in `owner_*.js` belegt (mit dem iframe-Element).
- Fehler werden nur als `throw new Error('<CODE>')` geworfen, mit einem Code aus `ScriptError`.
- Gemeinsamer Zustand liegt nur unter `globalThis.__browserrig` (`{dom, elements, stability}`) und ist im README beschrieben.

Damit sind die Skripte nicht mehr über `observation/` und `readiness/` verteilt, und `tools/` lädt keine Dateien mehr aus `observation/scripts`.

**Schritt 2: ein Loader mit Helfer-Einbindung**

CDP bekommt jede Funktion als einzelnen String, Imports gibt es nicht. Statt eines Bundlers reicht es, die benötigten `lib/`-Dateien in eine Wrapper-Funktion einzusetzen:

```python
# browserrig/scripts/__init__.py
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

_ROOT = files(__package__)


@cache
def _source(path: str) -> str:
    return _ROOT.joinpath(path).read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Script:
    name: str
    declaration: str  # exactly what Runtime.callFunctionOn receives

    @classmethod
    def load(cls, name: str, *, uses: tuple[str, ...] = ()) -> "Script":
        main = _source(f"{name}.js")
        if not uses:
            return cls(name, main)
        helpers = "\n".join(_source(f"lib/{helper}.js") for helper in uses)
        # Helpers become locals of the wrapper; `this` and the argument pass through.
        return cls(name, f"function(args) {{\n{helpers}\nreturn ({main}).call(this, args);\n}}")


SNAPSHOT = Script.load("snapshot", uses=("geometry", "composed", "visibility", "hit"))
ELEMENT = Script.load("element", uses=("elements",))
SCROLL = Script.load("scroll", uses=("geometry", "composed", "elements"))
SCROLL_OWNER = Script.load("scroll_owner", uses=("geometry", "composed"))
CONTENT = Script.load("content", uses=("composed", "visibility"))
CANVAS = Script.load("canvas", uses=("visibility",))
STABILITY = Script.load("stability")
SEED = Script.load("seed")
RESET = Script.load("reset")
PAGE_FACTS = Script.load("page_facts")
VIEWPORT = Script.load("viewport")
OWNER_SIZE = Script.load("owner_size", uses=("composed", "visibility"))
OWNER_HITS = Script.load("owner_hits", uses=("hit",))
```

Damit `no-undef` weiter greift, deklariert jede Hauptdatei ihre Helfer im Kopf (`/* global intersect, parentFor */`). Optional liest der Loader genau diese Zeile aus, statt `uses=` in Python zu pflegen. Dann steht die Abhängigkeit nur an einer Stelle, direkt am Code.

**Schritt 3: ein Ausführungsweg mit einheitlichen Fehlern**

```python
class ScriptError(StrEnum):
    STALE_ELEMENT = "STALE_ELEMENT"
    ELEMENT_BLOCKED = "ELEMENT_BLOCKED"
    ELEMENT_DISABLED = "ELEMENT_DISABLED"
    NOT_EDITABLE = "NOT_EDITABLE"
    OPTION_NOT_FOUND = "OPTION_NOT_FOUND"
    NOT_A_SELECT = "NOT_A_SELECT"
    INVALID_VALUE = "INVALID_VALUE"


class Frame:
    async def run(
        self, script: Script, args: object = None, *, objects: Sequence[str] = (), by_value: bool = True
    ) -> Any:
        """Run a script in this frame's isolated world."""
        return await _call(
            self.cdp, script, args, objects, by_value, execution_context_id=await self.context()
        )

    async def run_on_owner(self, script: Script, args: object = None) -> Any:
        """Run a script with `this` bound to the element that embeds this frame."""
        async with self._owner_object() as object_id:   # resolve_node + release_object
            return await _call(self.parent.cdp, script, args, (), True, object_id=object_id)


async def _call(cdp, script, args, objects, by_value, **target) -> Any:
    result = await cdp.runtime.call_function_on(
        function_declaration=script.declaration,
        arguments=[CallArgument(value=args), *(CallArgument(object_id=o) for o in objects)],
        return_by_value=by_value,
        await_promise=True,
        **target,
    )
    if result.exception_details:
        raise _script_error(script, result.exception_details)
    return result.result.value if by_value else result.result
```

`_script_error` übersetzt einen bekannten `ScriptError`-Code in `BrowserError(code)` und alles andere in `BrowserError(f"{script.name} failed in the page")`. Das gilt für alle Skripte gleich, also auch für den Owner-Modus.

Danach fallen weg: `Frame.evaluate`, `Tab.evaluate`, `Frame.call`, `Frame.owner_call`, `script_call` und der rohe `call_function_on` in `observation/dom.py`. Der Seed übergibt seine DOM-Knoten über `objects=`, läuft also über denselben Weg. Wichtig dabei: `user_gesture=True` setzt `Frame.call` heute für alle Skripte. Das sollte ein expliziter Parameter von `run` werden und nur für `element.js` (Fokus, Select) gesetzt sein.

**Schritt 4: Helfer zusammenführen**

```js
// lib/visibility.js – uses parentFor from lib/composed.js
function isRendered(el) {
  if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) {
    return false;
  }
  for (let current = el; current; current = parentFor(current)) {
    if (current.inert) {
      return false;
    }
  }
  return true;
}
```

Damit ist der `visibility`-Fehler aus 7.3 (Punkt 1) an allen vier Stellen auf einmal behoben, und `owner_size.js`, `snapshot.js`, `content.js` und `canvas.js` teilen dieselbe Definition. Genauso bekommen der Hit-Test (`lib/hit.js`) und die Element-Auflösung (`lib/elements.js`) je genau eine Implementierung. `element.js` braucht dann nicht mehr die `pointFor`-Closure aus dem Snapshot, sondern nutzt `lib/hit.js` direkt. Die versteckte Kopplung über `__browserrigElements.pointFor` verschwindet.

**Schritt 5 (optional): typisierte Skripte**

Heute validiert jeder Aufrufer das Ergebnis selbst (`DOMExtraction.model_validate`, `CanvasProbe.model_validate`, `DOMProbe.model_validate`, `_ScrollPlan.model_validate`, `PageFacts.model_validate`, `_Extraction.model_validate`). Das lässt sich in den Script-Typ ziehen:

```python
@dataclass(frozen=True, slots=True)
class TypedScript[A: BaseModel, R: BaseModel]:
    script: Script
    args: type[A]
    result: type[R]


class SnapshotArgs(Options):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    token: str
    max_elements: int | None
    max_text: int
    clip: Bounds | None = None


SNAPSHOT = TypedScript(Script.load("snapshot", uses=(...)), SnapshotArgs, DOMExtraction)


class Frame:
    async def query[A: BaseModel, R: BaseModel](self, typed: TypedScript[A, R], args: A) -> R:
        raw = await self.run(typed.script, args.model_dump(by_alias=True, mode="json"))
        return typed.result.model_validate(raw)


# Aufruf (heute capture.py:88-97)
extraction = await frame.query(
    SNAPSHOT,
    SnapshotArgs(token=snapshot_id, max_elements=max_elements, max_text=max_text, clip=frame.local_clip),
)
```

Nebenbei verschwindet das viermal kopierte `frame.local_clip.model_dump() if frame.local_clip else None` (2.3), weil Pydantic `Bounds | None` selbst serialisiert. JS-Argumente und Python-Modell können dann auch nicht mehr unbemerkt auseinanderlaufen.

**Schritt 6: absichern.** Siehe 8.3: Ein Test lässt kein Inline-JS mehr zu, ein weiterer prüft die Skriptform, ein dritter gleicht die JS-Fehlercodes mit `ScriptError` ab.

### 7.5 Reihenfolge

1. `scripts/`-Paket mit `Script.load` anlegen und die sechs Dateien dorthin verschieben. Das ist rein mechanisch.
2. Die Inline-Snippets als Dateien anlegen, `dom.js` zur Funktion machen und `script_call` entfernen.
3. `Frame.run` und `run_on_owner` einführen, die alten Aufrufwege ersetzen und die Fehlercodes vereinheitlichen.
4. Alle Argumente auf ein Options-Objekt umstellen und `scroll.js` aufteilen.
5. `lib/` einführen, die Duplikate abbauen und dabei `checkVisibility` übernehmen. Das ist der einzige Schritt mit Verhaltensänderung (Sichtbarkeit). Genau dafür sind die Chrome-Integrationstests da.
6. Optional: `TypedScript`.

Die Schritte 1–3 lassen sich zusammen mit den Contract-Tests aus 8.3 in einem PR erledigen.

---

## 8. Tests und Beispiele

### 8.1 Gesamteindruck

- 26 Testdateien mit rund 3.800 Zeilen. 13 davon laufen gegen echten Chrome (`pytest -m integration`, eigener CI-Job). Damit sind die JS-Skripte realistisch abgedeckt. JS-Unit-Tests in jsdom würden kaum etwas bringen, weil jsdom kein Layout hat (`getBoundingClientRect` und `elementFromPoint` liefern dort nichts Sinnvolles). Die Entscheidung für Integrationstests ist also richtig.
- Die Testnamen beschreiben Verhalten, z. B. `test_prevented_wheel_scroll_does_not_jump_or_click_an_unreached_target`. 👍
- Die CI ist gut aufgestellt: Python 3.12–3.14 auf Linux und Windows, ESLint und Prettier, dazu ein eigener Chrome-Job. 👍

### 8.2 Lücken und Auffälligkeiten

1. ✅ ~~**Der Canvas-Test verdeckt Bug 3.**~~ Erledigt: Die Canvas-Readiness prüft keine DOM-Ruhe mehr. Der Test setzt nur noch `tab.quiet_ms = 0` (`test_readiness.py:92`). Diese Zeile ist jetzt überflüssig und kann weg.
   - Listener: `_attach` wirft bei `TargetInfoChanged`, und der Browser bleibt trotzdem benutzbar (Bug 2). Das Muster gibt es schon in `test_missing_download_does_not_break_browser_listener`.
   - `close_tab`, wenn `tabs()` das geschlossene Target noch liefert (3.2, Punkt 2).
   - Genau ein `TabOpenedEvent` pro `open_tab` (3.2, Punkt 1).
4. **`FakeTab.evaluate` ignoriert das Skript** (`tests/fakes.py:21`) und liefert immer ein DOM-Probe-Ergebnis. Sobald ein zweiter Aufruf über `evaluate` läuft, liefert der Fake stillschweigend falsche Daten. Mit `Frame.run(script, args)` kann der Fake nach `script.name` verzweigen und bei unbekannten Skripten laut fehlschlagen.
5. **Viele Tests greifen auf private Attribute zu** (`_state`, `_browser`, `_metadata`, mit `pylint: disable=protected-access` in mehreren Dateien). Für Lifecycle-Tests ist das vertretbar, aber es verteuert Refactorings. Wo es geht, sollte man über Events aus dem `SessionLog` prüfen. Das ist ja gerade die Stärke der Architektur.

### 8.3 Contract-Tests

Diese Tests sind schnell geschrieben und sichern die Abstraktion aus Abschnitt 7 dauerhaft ab:

```python
# tests/test_scripts.py
import ast
import re
from pathlib import Path

import browserrig
from browserrig.scripts import ScriptError

ROOT = Path(browserrig.__file__).parent
SCRIPTS = ROOT / "scripts"
_JS_HINT = re.compile(r"\bfunction\s*\(|=>|globalThis\.|document\.\w|innerWidth")


def test_python_contains_no_inline_javascript():
    offenders = [
        f"{path.relative_to(ROOT)}:{node.lineno}"
        for path in ROOT.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _JS_HINT.search(node.value)
    ]
    assert not offenders, f"JavaScript belongs in browserrig/scripts/*.js: {offenders}"


def test_every_script_is_one_matching_function_declaration():
    for path in SCRIPTS.glob("*.js"):
        name = "browserrig" + "".join(part.title() for part in path.stem.split("_"))
        source = re.sub(r"^\s*/\*.*?\*/\s*", "", path.read_text(encoding="utf-8"), flags=re.S)
        assert source.startswith(f"function {name}("), path.name


def test_thrown_codes_are_known_script_errors():
    thrown = {
        code
        for path in SCRIPTS.rglob("*.js")
        for code in re.findall(r"new Error\('([A-Z_]+)'\)", path.read_text(encoding="utf-8"))
    }
    assert thrown <= {code.value for code in ScriptError}
```

Die Heuristik im ersten Test ist absichtlich grob. Gibt es Fehlalarme, ergänzt man eine kleine Allowlist.

### 8.4 Beispiele

- Die Beispiele sind klein und lesbar, und jedes nennt seine Aufrufzeile im Docstring. 👍 `openai_agent --help` läuft in der CI.
- `examples/direct_browser.py:8` importiert `browserrig.observation.capture.capture`, also ein internes Modul. Entweder ist `capture` öffentliche API, dann gehört es in `browserrig/observation/__init__.py` (`__all__`). Oder das Beispiel sollte den öffentlichen Weg zeigen. Beispiele sind die Doku der öffentlichen API, und ein interner Import dort zeigt, dass eine Export-Entscheidung fehlt.
- Nur `openai_agent` wird in der CI gestartet. `direct_browser` braucht keinen API-Key und würde sich als schneller Smoke-Test im Chrome-Job anbieten.
