# Browserrig — Spezifikation

Stand: laufende Implementierung des Browserkerns. Diese Datei beschreibt die
vereinbarte Architektur und benennt die Grenzen des aktuellen Arbeitsstands.

## Ziel

Browserautomation mit **Harnessed, cdpify und Pydantic v2**. Browserrig kann Chrome
starten oder einen laufenden CDP-Browser verbinden, Seiten beobachten und bedienen,
sachliche Hinweise erzeugen und native Videoaufnahmen mit einer Aktivitätszeitachse
speichern. Persona, Mental Model und Usability-Auswertung gehören nicht dazu.

## 1. Ein Browser-Seam, konkrete Verantwortlichkeiten

- `Browser` ist der gemeinsame Protocol-Vertrag.
- `ChromeBrowser` implementiert ihn und besitzt Verbindung, Browserkontext,
  Targets und gegebenenfalls den selbst gestarteten Prozess.
- `Chrome` ist das kleine Harnessed-Plugin, das eine `ChromeBrowser`-Instanz
  öffnet und als `Browser` bereitstellt.
- `Tab` hält eine feste Target-ID und eine feste cdpify-Session.
- `Frame` ist ein interner CDP-Begriff für das Hauptdokument oder ein eingebettetes
  iframe. Jeder Frame hat einen eigenen JavaScript-Ausführungskontext.

Es gibt keinen delegierenden `BrowserSession`-Wrapper und keinen
`FocusedTabClient`. Eine Aktion bindet ihren Tab einmal. Ein Fokuswechsel
leitet eine laufende CDP-Operation nicht auf einen anderen Tab um.

`tab.press_key(...)` sendet Tastatureingaben an die Seite dieser Target-Session.
Browserleisten- und Betriebssystemautomation sind eine andere Zuständigkeit.

Direkte Nutzung funktioniert ohne Agent:

```python
async with ChromeBrowser(LaunchBrowser(url="https://example.com")) as browser:
    tab = browser.active_tab
    report = await wait_for_page(browser, tab)
    print(await tab.evaluate("document.title"))
```

`wait_for_page` ist dieselbe fachliche Readiness-Funktion, die das Plugin verwendet.

## 2. Harnessed bleibt die Laufzeit

Harnessed besitzt Agentenloop, Toolregistry, Schemas, Policies, Approvals, Turns,
Controls und das append-only Session-Log. Browserrig ersetzt diese Mechanismen nicht.

`BrowserAgent` ist die Kompositionsfassade für die übliche Agentennutzung. Sie spezialisiert
Harnesseds `Agent` ausschließlich im Konstruktor: `browser`, `mode`, `readiness` und
`recording` konfigurieren `browser_plugins()`. `session_directory` aktiviert optional
`JsonlSessions`; `approvals`, `instructions` und zusätzliche `plugins` bleiben explizit.
Ohne diese Optionen gelten In-Memory-Speicherung und Harnesseds Approval-Default `ASK`.
Es gibt keine zusätzliche Run-/Session-Implementierung. Modellanbieter und Ressourcen
bleiben in ihrer bestehenden Ownership; eine Browserressource entsteht erst beim Session-Mount.
Native Pydantic-AI-Modelle können direkt übergeben werden, weil Harnessed sie adaptiert.
`browser_plugins()` und die einzelnen Fähigkeiten bleiben für eigene Komposition erhalten.

| Fähigkeit | Verantwortung |
| --- | --- |
| `Chrome` | konkrete Browserressource öffnen und zuverlässig schließen |
| `Readiness` | Prüfungen teilen, Dokumentbezug und Capture-Geometrie verwalten |
| `Observe` | Readiness, Aufnahme des Zustands und Projektion vor dem Modellschritt |
| `Actions` | Aktionsgrenze: Serialisierung, Readiness, einmaliger Dispatch und Receipts |
| `NavigationTools` | Navigation, Suche, Verlauf und Reload |
| `InteractionTools` | DOM-Klick, Doppelklick und Drag plus Koordinaten, Tastatur und Scrollen |
| `PointerTools` | Koordinatenklick/-doppelklick, Drag, Tastatur und Scrollen ohne DOM-Referenzen |
| `FormTools` | Text, native Auswahl und Datumsfelder |
| `TabTools` | kontrollierte Tabs auflisten, öffnen, wechseln und schließen |
| `FileTools` | Uploads und Downloadinformationen |
| `DialogTools` | blockierende Dialoge ohne Readiness-Abhängigkeit behandeln |
| `Nudges` | Ereignisse auswerten, Hinweise begrenzen und gültige Hinweise projizieren |
| `Recording` | native CDP-Aufnahmen und Artefaktabschluss |
| `Activity` | Modell-, Tool-, Readiness- und Pauseintervalle aus Events ableiten |

`Actions` ersetzt das Durchreichen von Browser, Readiness und Observation an jede
freie Hilfsfunktion. Tools injizieren die verantwortliche Fähigkeit und verwenden
benannte Parameter:

```python
return await actions.run(
    kind=ActionKind.CLICK,
    operation=click,
    expects_change=True,
)
```

Ein neues Service-Objekt ist nur gerechtfertigt, wenn es tatsächlich Zustand oder
einen fachlichen Ablauf besitzt. Die Kompositionsfassade `BrowserAgent` fügt keinen
eigenen Laufzeitzustand hinzu; weitere delegierende Controller-/Manager-Schichten entfallen.

Plugin-Rezepte enthalten Konfiguration. Veränderlicher Zustand entsteht pro Mount
durch `PluginState` oder in `setup`. `needs` und `Inject` beschreiben Abhängigkeiten;
`ctx.effect`/`ctx.enter` besitzen Cleanup. Zwei Sessions teilen keinen Laufzeitzustand.

## 3. Typen und Quellcodestil

- Geschlossene Werte werden mit `StrEnum` modelliert: Browser- und Beobachtungsmodus,
  Readiness-Zustand/-Phase, Aktionsart, Aktivitätsart/-ausgang und Event-Tags.
- Konfigurations-Unionen verwenden `Literal[Enum.MEMBER]` als Diskriminator.
- Öffentliche Daten, Extraktionsergebnisse, YAML-Ansicht, Fingerprint-Eingaben,
  Recording-Segmente und Manifest sind Pydantic-Modelle.
- Die agentensichtbare Darstellung hat ein eigenes Schema; interne Frame-/Index-
  Angaben gelangen nicht durch ad-hoc `exclude={"..."}`-Listen ins Modellformat.
- Rohe CDP-/JavaScript-Antworten werden an der Grenze validiert. Dynamisches
  `evaluate(...)` bleibt naturgemäß eine untypisierte Browsergrenze.
- Event-Auswertung und Replay verwenden `match/case`.
- Rückgaben von `self` beziehungsweise geeigneten Klassenmethoden verwenden `Self`.
- Imports stehen auf Modulebene. Lokale Imports brauchen einen konkreten Grund,
  etwa eine tatsächlich optionale Abhängigkeit oder einen unvermeidbaren Zyklus.
- Implementierungsdetails wie die Suche des Chrome-Binaries bleiben privat.

## 4. Ereignisse: stabile Namespaces und eindeutige Klassennamen

Alle konkreten Ereignisklassen enden auf `Event` und lassen sich direkt importieren.
Ihre Wire-Tags bleiben unabhängig vom Python-Klassennamen.

```python
class EventKind(StrEnum):
    ACTION_STARTED = "browser.action.started"

@dataclass(frozen=True, slots=True)
class ActionStartedEvent(BrowserEvent):
    action_id: str
    kind: ActionKind
    type: Literal[EventKind.ACTION_STARTED] = field(
        default=EventKind.ACTION_STARTED, kw_only=True
    )

@hook(ActionStartedEvent)
async def on_start(self, event: ActionStartedEvent) -> None:
    ...
```

Harnessed erwartet unveränderliche Dataclass-Records für seine Event-Registry.
Deshalb sind Events gefrorene Dataclasses; Pydantic validiert die übrigen
Datenverträge und die serialisierten Artefakte.

| Familie | Wire-Tags |
| --- | --- |
| Browser | `browser.connected`, `browser.disconnected` |
| Tabs | `browser.tab.opened`, `.activated`, `.closed` |
| Navigation | `browser.navigation.started`, `.committed` |
| Aktionen | `browser.action.started`, `.finished`, `.failed` |
| Readiness | `browser.readiness.started`, `.ready`, `.degraded`, `.failed`, `.cancelled` |
| Beobachtung | `browser.observation.captured` |
| Dialog/Download | `browser.dialog.opened`, `.handled`, `browser.download.completed` |
| Nudges | `browser.nudge.queued`, `.included`, `.expired` |
| Aufnahme | `browser.recording.started`, `.segment.closed`, `.finished`, `.failed` |
| Aktivität | `browser.activity.started`, `.finished` |

Records tragen Browser-, Target-, Dokument- und passende Korrelations-IDs.
Aktivität erhält zusätzlich eine Zeitepoche: monotone Zeiten verschiedener
Prozessläufe werden nicht als eine gemeinsame Uhr behandelt.

CDP-Signale aktualisieren zuerst den Browserzustand. Fachliche Übergänge werden
über Harnessed veröffentlicht. Hochfrequente DOM-Mutationen und Video-Binärdaten
werden nicht als einzelne dauerhafte Records gespeichert. Ein Event ist kein
verdeckter Request/Response-Aufruf.

Erzeugende Plugins deklarieren ihre Eventtypen vor dem Öffnen gespeicherter Logs.
Replay rekonstruiert Daten, ohne alte Browseraktionen oder Aufnahmen auszuführen.

## 5. DOM und Canvas sind zwei explizite Modi

`WebMode` und `FigmaMode` sind diskriminierte Konfigurationen. Der gewählte Modus
bestimmt Readiness, Erfassung, Bildprojektion und angebotene Tools.

### DOM

Erfasst werden sichtbarer Text, interaktive Elemente und Semantik einschließlich
Labels, Zuständen und nativen Optionen. Open Shadow DOM und inspizierbare Frames
werden berücksichtigt. Passwortwerte werden nicht aufgenommen.

Elementreferenzen gehören zur letzten Beobachtung, zum Tab und zum Dokument.
Eine Referenz auf ein anderes Dokument oder ein entferntes Element wird verworfen.
Vor dem Klick wird das konkrete Element erneut aufgelöst und auf Überdeckung geprüft.

### Canvas

Initial müssen Canvas, sichtbare Geometrie und Bildinhalt bereit sein. Leere
Bilder und typische spärliche zentrale Loading-Grafiken bestehen die Pixelheuristik
nicht. Capture-Grenzen müssen in zwei Prüfungen stabil sein.

Bestätigte Geometrie wird pro Dokument wiederverwendet. Spätere Loading-Bilder
dürfen beobachtbar bleiben; die volle Initialprüfung wird nicht bei jedem Screenshot
wiederholt. Geometriewechsel invalidiert den Cache.

Canvas bietet Koordinaten-, Tastatur- und Scrolltools. DOM-Referenz- und Formtools
werden in dieser Komposition nicht registriert. Eine benutzerdefinierte
`selector`-Konfiguration kann einen bestimmten sichtbaren Inhaltsbereich wählen.

Automatische Figma-Geräterahmenerkennung und deren vollständige Regressionen
bleiben ein gesonderter Abnahmepunkt; die aktuelle generische Canvas-Heuristik
behauptet keine sichere Erkennung jedes Figma-Viewerlayouts.

## 6. Readiness und Beobachtungsreihenfolge

Readiness gilt pro Browser, Target, Dokument und Modus. Initiale Prüfung,
Navigation und Aktion besitzen explizite Phasen und begrenzte monotone Deadlines.
Konkurrierende Wartende teilen eine laufende Prüfung. Cancellation eines Wartenden
beendet nicht die noch benötigte Prüfung eines anderen.

DOM-Readiness kombiniert Lifecycle-/Dokumentsignale, Body-Verfügbarkeit und
Mutationsruhe. `DOMContentLoaded` allein genügt nicht. Ein endloser Ticker kann
nach Ablauf des Budgets ausdrücklich `DEGRADED` ergeben; initialer Canvas-Timeout
bleibt ein Fehler.

Ein offener Dialog ergibt `BLOCKED` und bleibt für `DialogTools` behandelbar.
Die Wartelogik darf nicht auf genau das Tool warten, das die Blockade auflöst.

Vor jedem Modellschritt:

```text
Harnessed-Control-Checkpoint
  → Readiness
  → konsistente Beobachtung
  → ObservationCapturedEvent und Nudge-Regeln
  → gültige Hinweise auswählen
  → session.observe(...) für YAML und Hinweise
  → PrepareRequest ergänzt das aktuelle Bild, falls nötig
  → Harnessed protokolliert und budgetiert den Request
```

Harnesseds `Observation` ist textuell. Bilder werden nativ als `ImagePart` über
`PrepareRequest` oder einen multimodalen `ToolResult` übergeben.

Das YAML kommt aus `SnapshotView`, `PageView` und `ViewportView`:

```yaml
page:
  tab: tab-1
  document: doc-7
  url: https://example.org/contact
  title: Kontakt
  mode: web
  readiness: ready
viewport:
  width: 1280
  height: 800
  scroll_y: 0
elements:
  - ref: abc12345:0
    role: textbox
    name: E-Mail
    tag: input
```

YAML ist ein Datenformat, keine Template- oder Ausführungssprache.
`PageFingerprint` und `ElementFingerprint` bestimmen typisiert den Vergleich;
zufällige Beobachtungs-IDs verändern den Fingerprint nicht.

## 7. Aktionen und Nudges

`Actions` serialisiert mutierende Operationen, prüft Readiness und veröffentlicht
Start/Ergebnis/Fehler. Mutationen werden nicht automatisch wiederholt. Nach einem
möglicherweise ausgeführten Submit muss ein späterer Beobachtungsfehler ausdrücklich
erkennen lassen, dass die Aktion bereits gelaufen sein kann.

`Nudges` wertet passende Ereignisse aus und hält Kandidaten mit Ursache,
Gültigkeitsbereich und Deduplizierungsschlüssel. Anzahl und Textbudget sind begrenzt.
Normale Hinweise verwenden `Observation`, keine künstliche Steuerungsnachricht.

- `NoProgress`: eine erwartete Wirkung fehlt in der nächsten stabilen Beobachtung.
  Download, Dialog oder neuer Tab können eine Wirkung sein, auch ohne DOM-Änderung.
- `UnexpectedScroll`: nur nach Klick, bei exakt gleicher URL, gleichem Dokument
  und gleichem Target. Query-/Fragmentwechsel unterdrücken den Hinweis ebenfalls.
  Selbst ausgelöstes Scrollen zum Erreichen des Elements wird ignoriert.
- Tab-, Download-, Dialog- und Readiness-Hinweise bleiben sachlich.

`NudgeQueuedEvent` bedeutet keine Modellzustellung. Erst der tatsächlich
protokollierte Modellrequest begründet `NudgeIncludedEvent`. Veraltete oder schon
verwendete Hinweise werden beim Reopen nicht erneut ungeprüft zugestellt.

## 8. Start, Attach und Besitz

### Doppelklick und Drag

Doppelklick verwendet native Click-Counts. Drag hat den geschlossenen Modus
`DragMode.POINTER` oder `DragMode.HTML5`; letzterer transportiert die vom Browser
abgefangenen nativen DragData über CDP-DragEnter/DragOver/Drop.
DOM-Quellen mit `draggable=true` wählen HTML5 automatisch. Beide DOM-Endpunkte
müssen gleichzeitig sichtbar sein. Maustasten und temporäre Drag-Interception
werden auch bei Cancellation zurückgesetzt. Koordinatengesten binden sich an die
aktuelle Beobachtung; ein Dokument-/Tabwechsel macht alte Ziele ungültig.

`LaunchBrowser` und `ConnectBrowser` sind Pydantic-Konfigurationen mit
`BrowserKind`. Start verwendet ein eigenes temporäres Profil und einen vom Browser
gewählten Debugging-Port. Die Chromium-Sandbox wird nicht pauschal abgeschaltet.

Connect akzeptiert HTTP(S)-Discovery oder einen Browser-WebSocket. Ein Page-WebSocket
wird nicht als Browser-Endpunkt behandelt. `SecretStr` schützt Endpunkt-/Headerreprs.

Standard beim Connect ist ein eigener isolierter Kontext. Mit `target_id` wird ein
vorhandener Tab ausdrücklich gewählt. Cleanup beendet selbst gestartete Prozesse,
erhält jedoch fremde Browserprozesse und fremde Tabs.

Ein laufender Browser muss CDP bereits anbieten. Browserrig aktiviert Remote
Debugging nicht nachträglich in einem beliebigen Benutzerprozess.

Dateipfade für Uploads und Downloads beziehen sich auf den Browserhost. Remote
Dateitransfer gehört in einen expliziten Hostadapter.

## 9. Native Aufnahme und Aktivität

Die Baseline verwendet cdpifys `page.start_screen_recording(...)` und
`stop_screen_recording()`. Ergebnisstreams werden mit begrenzten `IO.read`-Chunks
übernommen und zuverlässig geschlossen. Ein obligatorischer JPEG-/ffmpeg-Pfad entfällt.

- Start nach erfolgreicher Initial-Readiness und vor der ersten Aktion.
- Der Browser kodiert die Videozeitachse; lokale monotone Start-/Stopbezüge stehen
  im Manifest.
- Tabwechsel und optional bestätigte Pausen erzeugen explizite Segmente.
- Dateigröße, Streamende, Container und Prüfsumme werden kontrolliert.
- Artefakte werden zuerst temporär geschrieben und danach atomar veröffentlicht.
- `required=False` erlaubt einen klar gemeldeten Aufnahmefehler; `required=True`
  macht die Aufnahme zu einer Voraussetzung.
- Native Aufnahme ist viewportbezogen. Canvas-Geometrie steht als Bezug im Manifest;
  ein physisch zugeschnittenes Video wird nicht vorgetäuscht.
- Recording endet bei explizitem Abschluss/Sessionende und wird vor dem
  CDP-Disconnect finalisiert.

`RecordingManifest`, `RecordingSegment` und `TimeRange` sind Pydantic-Modelle.

`Activity` beobachtet Modellrequest/Assistant-Receipt, Toolreceipts, Readiness und
bestätigte Controls. Das LLM wird dafür nicht dekoriert. `ActivityKind` ist derselbe
Enum-Typ im Event und in der Projektion.

Offene Intervalle sind durch `ActivityKey(kind, correlation_id)` adressiert. Modellwartezeit
und Pause besitzen je einen Slot ohne Korrelations-ID; Tool- und Readiness-Intervalle
erfordern ihre eigene ID. Identische ID-Texte verschiedener Aktivitätsarten kollidieren nicht.
Ein erneuter Start desselben Slots beendet nur dessen Vorgänger mit `SUPERSEDED`.

`ActivityFinishedEvent.outcome` ist ein validierter `ActivityOutcome`-Enum.
Readiness-Endereignisse und Harnesseds Step-/Turn-Enums bestimmen den Ausgang explizit;
freie Diagnosetexte stehen ausschließlich in `reason`. Fehlerhafte Toolreceipts ergeben
`FAILED`. Turn-Ende beendet offene Arbeit, aber keine bestätigte Pause; Session-Cleanup
schließt verbleibende Intervalle mit `CLOSED`. Liveansicht und Replay verwenden dieselbe
Intervallprojektion.

Bekannte bisherige Outcome-Werte wie `completed` bleiben beim Laden gültig; ein fehlendes
`reason` wird als leer behandelt. Alte Records, die freien Readiness-Text in `outcome`
gespeichert haben, benötigen eine Migration anhand der zugehörigen Readiness-Endereignisse.
Unbekannte Outcome-Werte werden nicht als gültige Zustände akzeptiert.

Gemessen wird clientseitige Modellwartezeit einschließlich Netzwerk/Streaming.
Die Projektion `inference_only` zieht überlappende Tool-, Readiness- und Pausezeit
ab. Diese Zeitbereiche stehen zusätzlich zum unveränderten Originalvideo im Manifest.

## 10. Steering, Pause, Resume und Reopen

Verwendet werden direkt Harnesseds `submit`, `steer`, `pause`, `resume`, `stop`
und `abort`.

- Pause bestätigt die vollständige Schrittgrenze. Sie friert Chromium nicht ein.
- Verbindung, Browserereignisse und standardmäßig Aufnahme laufen weiter.
- Resume prüft und beobachtet die aktuelle Seite vor der nächsten Modellentscheidung.
- Steering während Pause wird bis Resume gehalten.
- Stop beendet die Runde geordnet; Abort unterbricht Modell/Tools und drainiert Cleanup.
- Cancellation eines `handle.result()`-Wartenden ist kein Aufgabenabbruch.
- Ein Hook/Tool darf nicht auf seine eigene Pausegrenze warten.

Persistierte Konversation und lebender Browser sind getrennte Ressourcen.
Reopen ermittelt Sessions/Targets neu, verwirft alte Elementreferenzen und beginnt
eine neue Zeitepoche. Ein neues Video beginnt ein neues Segment. Abgeschlossene
Browseraktionen werden beim Log-Replay nicht blind wiederholt.

## 11. Beispiele und Modell

Ausführbare Beispiele liegen in `examples/`: direkter Browser, Connect, OpenAI-Agent,
Controls und Canvas. Agentenbeispiele lesen `OPENAI_API_KEY` und optional
`OPENAI_MODEL`; der Standard ist `gpt-6.1-terra`.

Das konkrete SDK-Modell ist `OpenAIResponsesModel`, eingebunden über Harnesseds
`PydanticAIModel`. Tool Calling dieses Modells verlangt die Responses API:
[offizielle Modellreferenz](https://developers.openai.com/api/docs/models/gpt-6.1-terra).

Providerzugang ist nur für echte Agentenläufe nötig. Tests verwenden
`ScriptedModel`/`CallbackModel` und lokale Seiten. Die Implementierungsprüfung
führt keine kostenpflichtigen Modellaufrufe aus.

## 12. Abnahme und Grenzen

Zum nachgewiesenen Kern gehören Event-Codec, Plugin-State-Isolation, Readiness-
Wartende/Degraded-Verhalten, URL-gebundene Nudges sowie echte Chrome-Tests für
Start/Connect, Agentenaktionen, Canvas, native Aufnahme und Controls.

Vor der Bezeichnung als vollständig produktionsreif bleiben gezielte Nachweise
für komplexe Figma-Viewer, transformierte/cross-process Frames, Prozesscrash-Recovery,
alle Datei-/Downloadfehler und eine breite Chromium-/Plattformmatrix erforderlich.
Diese Grenzen werden in README und Tests sichtbar gehalten.

Referenz: Harnessed-Commit `967380be850e349e52b67b4a094a995adff9602e`.
Die konkrete Auflösung der Abhängigkeiten steht in `uv.lock`.
