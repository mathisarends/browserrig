# Browserrig als komponierbares Harnessed-SDK

**Umsetzungsstand:** Variante B ist im Code umgesetzt. Die konkrete öffentliche API,
Erweiterungsverträge und Migration stehen in
[docs/browser-composition.md](docs/browser-composition.md). Die folgenden Abschnitte
halten die ursprüngliche Analyse und Entscheidung fest; beispielhafte App-Klassen
wie `FigmaLoaded` bleiben eigene Erweiterungen, keine mitgelieferten Implementierungen.

Stand: 30.10.2026, nach erneuter Codeprüfung aktualisiert. Grundlage ist der aktuelle Repository-Code mit der lokal installierten, im Projekt gepinnten Harnessed-Version **0.6.0**. Die ursprüngliche SDK-Prüfung erfolgte mit 0.5.0; die zentralen Plugin-, Beobachtungs- und Stream-Schnittstellen wurden nach dem Upgrade erneut geprüft. Dies ist ein Konzept, keine bereits implementierte API. Neue Namen in den Entwurfsbeispielen sind Vorschläge.

## Empfehlung

**Harnessed `Agent` bleibt der Composition Root. Browserrig liefert wenige zusammensetzbare Plugins, austauschbare Strategien und einfache Rezepte für häufige Varianten.** DOM, Canvas, Screenshot-Verhalten, Readiness und Darstellung sollen unabhängig wählbar sein. Ein Figma-Agent ist dann ein Rezept aus diesen Komponenten und eigenen App-Regeln.

Nicht jede kleine Entscheidung braucht ein Plugin: Lifecycle, Hooks, Tools und eigener Session-Zustand rechtfertigen Plugins. Capture-Verfahren, Renderer und Auswahlregeln können normale typisierte Python-Objekte sein. Dadurch bleibt die Architektur erweiterbar und im Code nachvollziehbar.

Mit „Baummodus“ ist hier die DOM-Beobachtung gemeint; das bestehende Figma-Beispiel dient als konkrete Canvas-Variante. Die erwähnte Bibliothek interpretiere ich als Harnessed. Dort ist XML eines der **Prompt-Ausgabeformate**, keine XML-basierte Dependency-Injection- oder Konfigurationssprache.

## 1. Wo die aktuelle Kopplung sitzt

| Stelle | Aktuelles Verhalten | Konsequenz |
| --- | --- | --- |
| [`composition.py`](browserrig/composition.py) | Installiert für DOM und Canvas dieselben Tool-Plugins | Varianten entstehen teilweise durch nachträgliches Ausblenden |
| [`core/modes.py`](browserrig/core/modes.py) | Geschlossene Union `DomMode \| CanvasMode`; Canvas erzwingt Screenshots | Neue Beobachtungsarten benötigen Änderungen an zentralen Fallunterscheidungen |
| [`observation/plugin.py`](browserrig/observation/plugin.py) | `Observe` übernimmt Capture, Zustand, Prompt, Textdarstellung, Bild-Injektion und Tools | Eigene Darstellung oder Bildhistorie berührt einen großen Baustein |
| [`observation/capture.py`](browserrig/observation/capture.py) | Gute interne Strategien, aber geschlossene Auswahl nach Modus | Eigene Capture-Implementierung ist kein öffentlicher Erweiterungspunkt |
| [`readiness/wait.py`](browserrig/readiness/wait.py) | Gemeinsamer Ablauf mit interner DOM-/Canvas-Auswahl und Sonderfall für Dateivorschauen | App-Readiness und Capture-Geometrie hängen am selben Modus |
| [`tools/execution.py`](browserrig/tools/execution.py) | `Actions` hält die gemeinsame Transaktion; Kettenprüfung unterscheidet DOM von anderen Modi | Neues Wahrnehmungsverfahren braucht auch eine passende Entscheidung über Aktionsketten |
| [`tools/mouse.py`](browserrig/tools/mouse.py) | DOM- und Koordinatenwerkzeuge in einer Klasse; DOM-Tools über `has_dom_refs` deaktiviert | Installierte Fähigkeiten und tatsächlich nutzbare Werkzeuge fallen auseinander |

Eine besonders konkrete Inkonsistenzgefahr: `Observe` verwendet für Prompt und Rendering `self.mode`, für Capture aber `Readiness.mode`. Manuelle Komposition muss heute beide identisch konfigurieren.

Es gibt bereits gemeinsame Fehlerbehandlung in `Actions.run()` und im Readiness-Ablauf. Diese sollte erhalten bleiben. App-spezifisch sind eher das Erkennen von Ladezuständen, die Auswahl des Bildausschnitts und die Darstellung der Beobachtung.

Auch DOM kann bereits Canvas-Flächen auflisten, Screenshots erzeugen und Koordinatenaktionen ausführen. „DOM oder Bild“ ist also schon heute keine echte fachliche Ausschließlichkeit.

## 2. Was Harnessed bereits mitbringt

Im installierten SDK geprüft:

| Mechanismus | Verwendung für Browserrig | Grenze |
| --- | --- | --- |
| `Agent(plugins=[...])` | Explizite Zusammenstellung im Anwendungscode | Browserrig muss geeignete Bausteine anbieten |
| `Plugin`, `Inject`, `needs`, `provides` | Services und deren Lifecycle verknüpfen | Injection allein erklärt keine Lifecycle-Abhängigkeit |
| `Service(KeyOrType, value)` | Eigene zustandslose Strategien einstecken | Mutable Konstruktorwerte sind nicht automatisch pro Session isoliert |
| `PluginState` | Bildpuffer, Snapshot, Readiness-Zustand pro Mount | Keine globalen Listen in wiederverwendbaren Rezepten |
| Plugin-`slot` | Eindeutige Rolle; explizite SDK-Defaults ersetzen | Zwei explizite Plugins im selben Slot erzeugen `PluginConflict`; kein allgemeines „letztes gewinnt“ |
| `PreStep`, `PrepareRequest` | Beobachten und Modellrequest zusammensetzen | Die Reihenfolge und Zuständigkeit mehrerer Hooks muss definiert bleiben |
| `SystemSection`, `system_section`, `SystemPrompt` | Anweisungen mit Fähigkeiten zusammensetzen | XML-Formatierung löst keine Capture- oder Lifecycle-Kopplung |
| `session.use()` | Fähigkeiten zeitweise montieren | Prompt-Sections benötigen eine explizite `SectionDelivery`; Wechsel kann abhängige Plugins neu starten |
| `LatestObservationOnly` | Vollständige aktuelle Textbeobachtung plus begrenzte Zusammenfassungen | Keine konfigurierbare Screenshot-Historie |

`Observation.full` ist im SDK ein **String**. Browserrig hängt das aktuelle Bild separat über `PrepareRequest` als `ImagePart` an. Eine Bilderfolge darf deshalb nicht als vermeintlich fertige Funktion von `LatestObservationOnly` geplant werden.

`Bundle` ist im geprüften SDK eine Sammlung von Hooks und Registrierungen, kein allgemeiner Container für verschachtelte Plugin-Listen. Rezepte sollten zunächst normale Funktionen sein, die eine flache Plugin-Liste liefern. Das hält auch Prompt- und Event-Deklarationen am Agent-Rand sichtbar.

## 3. Drei Architekturvarianten

| Variante | Aufbau | Vorteil | Nachteil |
| --- | --- | --- | --- |
| A: Strategien in bestehenden Plugins | `Observe(capture=..., renderer=..., images=...)`, `Readiness(initial=..., ongoing=...)` | Kleiner Umbau, wenige öffentliche Typen | `Observe` bleibt für mehrere Lifecycle-Aufgaben verantwortlich |
| B: Wenige Plugins plus Strategien | Readiness, Beobachtung, Bildkontext und Tool-Fähigkeiten getrennt; darunter normale Python-Strategien | Gute Erweiterbarkeit, klare Session-Zuständigkeit | Einige neue Verträge müssen sauber definiert werden |
| C: Alles als eigenes Plugin | Einzelne Plugins für DOM, Bilder, Crop, Marks, Timing, Filter, Rendering usw. | Sehr freie Laufzeitkomposition | Hook-Reihenfolge, Abhängigkeiten und widersprüchliche Konfiguration werden schnell kompliziert |

**Entscheidung: B direkt umsetzen.** Readiness, Beobachtung, Bildkontext und Tool-Fähigkeiten werden eigenständige Plugins; ihre austauschbaren Verfahren sind normale typisierte Python-Strategien. A ist keine Zwischenstufe. Die Tabelle dokumentiert die betrachteten Alternativen. Harnessed bleibt für Lifecycle, Dependency Injection, Events und Agent-Schleife zuständig.

## 4. Unabhängige Entscheidungen statt globalem Modus

Eine Variante sollte diese Fragen getrennt beantworten:

1. **Was lesen wir?** DOM-Elemente, Seitenmetadaten, Bilddaten oder eine Kombination.
2. **Welchen Bereich zeigen wir?** Viewport, bestimmtes Canvas, Region oder mehrere Flächen.
3. **Wann fotografieren wir?** Ein Screenshot pro Schritt oder nur nach einem Screenshot-Toolaufruf.
4. **Welche Bilder sieht das Modell?** Die letzten N Screenshots.
5. **Wann darf es weitergehen?** Initialisierung, Navigation, vor Eingabe und nach Eingabe getrennt behandeln.
6. **Wie stellen wir den Zustand dar?** Generisches DOM-Rendering, kompaktes visuelles Rendering oder Figma-spezifische Hinweise.
7. **Welche Werkzeuge bieten wir an?** DOM-Refs, Koordinaten, Tastatur, Navigation, Dateien und JavaScript als bewusst gewählte Fähigkeiten.

Ein Renderer konsumiert strukturierte Beobachtungsdaten. Er führt keine Browseraktionen aus und trifft keine Readiness-Entscheidungen. Eigene Fehlermeldungen entstehen aus strukturierten Ergebnissen; die generische Transaktion und das Weiterreichen von Cancellation bleiben zentral.

### Kleiner vorgeschlagener Schnitt

| Baustein | Verantwortung |
| --- | --- |
| `Chrome` | Browser-Lifecycle und technische Browser-Events; bestehend |
| `Readiness` | Gemeinsamer Wait-Ablauf mit separaten Initial- und laufenden Strategien |
| `Observe` | Kohärente Beobachtung erzeugen, veröffentlichen und aktuelle Aktionsgrundlage halten |
| `ImageContext` | Die letzten N Screenshots im Modellkontext halten |
| `Actions` | Serialisierung, Eingabe, Ergebnis, Fehler und Aktionsketten; bestehende Verantwortung behalten |
| Tool-Plugins | `DomTools`, `PointerTools`, `KeyboardTools` und weitere fachliche Gruppen |

Innerhalb von `Observe` reichen zunächst austauschbare Objekte für Capture, Screenshot-Konfiguration und Renderer. Für `Actions` ersetzt eine Strategie zur Fortsetzung von Aktionsketten den Test `snapshot.mode == DOM`. Wenn eine Prüfung unsicher ist, endet die Kette wie heute.

Fähigkeiten sollten aus den installierten Komponenten abgeleitet oder beim Aufbau validiert werden: DOM-Tools benötigen einen Ref-Resolver. Ein Modusname oder ein leeres `elements`-Array ist dafür kein hinreichender Test.

Dynamisches `enabled=` bleibt sinnvoll für **vorübergehende** Zustände, etwa fehlende aktuelle Beobachtung oder nicht verfügbare Dateien. Eine statische Variante ohne DOM-Fähigkeit installiert die DOM-Tools gar nicht.

## 5. Screenshots: Auslöser und Anzahl im Kontext

Die öffentliche Konfiguration beantwortet genau zwei Fragen:

| Einstellung | Bedeutung | Beispiel |
| --- | --- | --- |
| `trigger: ScreenshotTrigger` | Ein Screenshot bei jedem Agent-Schritt oder nur nach einem Screenshot-Toolaufruf | `EACH_STEP` oder `ON_REQUEST` |
| `keep_latest_n_screenshots: int` | Wie viele der jüngsten Screenshots im Modellkontext bleiben | `3`: die letzten drei Aufnahmen |

Der Auslöser ist ein `StrEnum` (API-Entwurf):

```python
from enum import StrEnum


class ScreenshotTrigger(StrEnum):
    EACH_STEP = "each_step"
    ON_REQUEST = "on_request"
```

`EACH_STEP` erzeugt vor jedem Modellaufruf eines Agent-Schritts einen aktuellen Screenshot. `ON_REQUEST` erzeugt ihn nur, wenn das Screenshot-Tool aufgerufen wurde; wie im bestehenden Ablauf erfolgt die Aufnahme an der nächsten Beobachtungsgrenze vor dem Modellaufruf. Ein Toolaufruf im Modus `EACH_STEP` erzeugt dort kein zweites Bild.

```python
Observe(
    capture=CanvasCapture(region=FigmaViewport()),
    renderer=FigmaRenderer(),
    screenshots=Screenshots(trigger=ScreenshotTrigger.EACH_STEP),
),
ImageContext(keep_latest_n_screenshots=3),
```

Für Aufnahmen ausschließlich auf Toolaufruf wird nur der Trigger durch `ScreenshotTrigger.ON_REQUEST` ersetzt.

`keep_latest_n_screenshots` ist eine positive ganze Zahl, vorgeschlagener Default: `1`. Nach jeder neuen Aufnahme fällt das älteste Bild heraus, sobald N überschritten wird. Alle bis zu N behaltenen Bilder werden bei jeder Modellanfrage chronologisch mitgegeben, jedes genau einmal. Ohne neue Aufnahme bleibt der Puffer unverändert.

Beispiel mit N=3 und `EACH_STEP`: Schritt 1 sieht Bild 1; Schritt 2 sieht Bilder 1 und 2; Schritt 3 sieht Bilder 1, 2 und 3; Schritt 4 sieht Bilder 2, 3 und 4. Bei `ON_REQUEST` zählen die tatsächlichen Aufnahmen, nicht die Agent-Schritte.

Der Puffer gehört in `PluginState`; Bilder behalten Aufnahmezeit, Tab-/Dokumentbezug und Geometrie. Ältere Bilder dienen dem Vergleich und sind keine aktuelle Koordinatengrundlage. Interne Readiness-Probes gelangen nicht in diesen Puffer. Toolresultat und Request-Aufbereitung dürfen dasselbe Bild nicht doppelt liefern. Dauerhafte Speicherung für Replay ist von dieser Kontextbegrenzung unabhängig.

## 6. Initial Readiness und laufende Readiness wirklich trennen

Heute existieren bereits `INITIAL`, `OBSERVATION`, `ACTION` und `NAVIGATION`. Das sind aber Phasen desselben Modus-/Optionssystems. `Observe._before_step` wählt `INITIAL` nur, solange überhaupt kein Snapshot existiert. Das ist keine vollständige Initialisierung pro neuem Dokument. Canvas leitet das größere Budget zudem aus dem Geometriecache ab.

Der Entwurf sollte zwei unabhängig konfigurierbare Aufgaben haben:

| Aufgabe | Wann? | Beispiel Figma |
| --- | --- | --- |
| `initial` | Vor der ersten nutzbaren Beobachtung eines Dokuments | App geladen, Ladeoverlay weg, relevante Zeichenfläche vorhanden |
| `ongoing` | Vor Beobachtung/Eingabe oder nach einer Mutation | Eingabe möglich, Layout ausreichend ruhig, Drag-Ergebnis sichtbar |

Beide nutzen denselben bewährten Wait-Runner für Deadline, Cancellation, Dialoge und Events. Unterschiedlich sind Strategie, Budget, Wiederholungsintervall und Umgang mit einem Timeout. Initialisierung braucht kein eigenes zweites Runtime-System.

Eine laufende Policy kann nach Anlass unterscheiden: `before_observation`, `before_action`, `after_action`, `after_navigation`. Das benennt insbesondere den Unterschied zwischen „darf ich klicken?“ und „ist das Ergebnis des Klicks schon sichtbar?“. Ein zusätzliches `settle`-Plugin ist dafür zunächst nicht erforderlich.

Vorgeschlagener Ablauf:

```text
Dokument noch nicht initialisiert
  -> initial.wait()
  -> bei Erfolg initialisierten Zustand merken
  -> Beobachtung aufnehmen

vor einer späteren Eingabe
  -> ongoing.wait(before_action)
  -> Eingabe genau einmal ausführen
  -> bei neuem Dokument: initial.wait() für dieses Dokument
  -> sonst ongoing.wait(after_action)
  -> neue Beobachtung nach Screenshot-/Beobachtungsplan
```

Die Initialisierungsmarke wird mindestens durch `(browser_id, tab_id, document_id)` bestimmt. Ein Tabwechsel innerhalb desselben Dokuments startet nicht automatisch die ganze App-Prüfung neu. Für SPAs ohne neue Dokument-ID kann eine App-Strategie eine explizite Generation oder Invalidierung liefern.

Ein fehlgeschlagener Initial-Check setzt keine Erfolgsmarke. Gleichzeitige Waits werden nur bei identischem Dokument, Anlass und Policy zusammengeführt. Wenn Policies austauschbar sind, müssen laufende Tasks und Caches bei einem Wechsel beendet oder passend versioniert werden.

Die Auswahl einer Screenshot-Region sollte vom Readiness-Ergebnis entkoppelt werden: dieselbe Region-Strategie darf von beiden benutzt werden, aber „bereit“ bedeutet nicht automatisch „genau dieses Bild aufnehmen“. Dateivorschauen erhalten über das Rezept beziehungsweise einen expliziten Selektor ihre eigene Strategie.

Das gilt auch für `initial`: Öffnet ein Figma-Agent ein heruntergeladenes Dokument, darf `FigmaLoaded` dort nicht auf die Zeichenfläche der App warten. Die dokumentbezogene Auswahl der Initial- und laufenden Strategie gehört von Anfang an zum Vertrag. Der bestehende Dateivorschau-Sonderfall muss beim Umbau erhalten und für eigene Strategien zugänglich werden.

## 7. Ein klarer Vertrag für Events und Stream

### Was das SDK heute tatsächlich macht

Die konkrete Streaming-API ist hier **`session.stream(...)`**, erreichbar über `agent.session()`. Der geprüfte `Agent` besitzt keine eigene `stream()`-Methode. Ein späteres `BrowserAgent.stream()` wäre eine zusätzliche Convenience-API.

Vier Dinge sind auseinanderzuhalten:

1. Internes Dispatch an Hooks.
2. Dauerhaftes Session-Log.
3. Live-Subscription über `session.subscribe(...)`.
4. Für einen Turn projizierter Stream über `session.stream(...)`.

| Event-Gruppe heute | Dauerhaft? | `subscribe()` | `subscribe(transient=True)` | `session.stream()` während des Turns |
| --- | --- | --- | --- | --- |
| Browser-, Action-, Readiness-, Observation-, Recording-, Nudge- und Activity-Events als `BrowserEvent` | Ja | Ja | Ja | Ja, als eigene `DurableEvent`-Typen |
| Cursor, Pointer, Keys, Scroll, Highlights und Waiting als `InputEvent` | Nein | Nein | Ja | Ja, als eigene transiente Events |
| SDK-Text-/Reasoning-Deltas, Tool-Previews, Modellversuche, Retry und laufende Compaction | Nein | Nein | Ja, wenn publiziert | Die explizit vorgesehenen Streamtypen |
| Native Session-Buchführung, z. B. `StepStartedEvent`, `ObservationsIncludedEvent` | Ja | Ja | Ja | Nicht automatisch; die Projektion leitet nicht jeden nativen Logtyp weiter |
| Turn-Start und Control-Wechsel | Ja | Ja | Ja | Werden zu Statusänderungen projiziert |
| `TurnFinishedEvent` | Nein | Kein gespeicherter Logeintrag | Nicht als allgemeines Subscribe-Abschlusssignal zugesichert | Wird bei normal ausgeschöpftem Stream erzeugt |

`harnessed.events.TransientEvent` ist dabei der öffentliche Alias für die Erweiterungsbasis `CustomTransientEvent`. Deshalb werden Browserrigs `InputEvent`-Unterklassen von der SDK-Projektion erfasst.

**Transient heißt nicht „intern“.** Eigene registrierte dauerhafte und transiente Events werden im Turn-Stream weitergereicht. `Plugin.events` ist ein Typkatalog für Registrierung und Validierung, keine konfigurierbare UI-Allowlist. Terminalausgabe ist nochmals ein eigener Consumer und definiert nicht den Stream-Vertrag.

Subscriptions liefern zukünftige Ereignisse. Setup-Ereignisse vor dem Beginn eines Turn-Streams sind deshalb nicht automatisch darin enthalten. Ein UI braucht bei Anschluss einen aktuellen Zustand; Browserrig veröffentlicht bereits den Cursorzustand am Turn-Start erneut.

### Eigene Events über die vorhandene SDK-Erweiterung

Die Anforderung ist: Browserrig und eigene App-Plugins können zusätzliche typisierte Events definieren, die im normalen Harnessed-Stream ankommen. **Das unterstützt Harnessed bereits; die Weitergabe eigener Events wurde auch im installierten 0.6.0-Code bestätigt.**

Der vorgesehene Weg:

1. Einen eigenen Eventtyp als unveränderliche Dataclass definieren, abgeleitet von `harnessed.events.DurableEvent` für gespeicherte Fakten oder `harnessed.events.TransientEvent` für reine Live-Mitteilungen.
2. Einen eindeutigen, namespaced `type`-Discriminator als `Literal` mit passendem Default deklarieren, beispielsweise `figma.selection.changed`.
3. Den Typ über `Plugin.events = (MyEvent,)` registrieren.
4. Das Event über den injizierten `SessionLog` mit `await log.emit(MyEvent(...))` veröffentlichen.
5. Im bestehenden `session.stream(...)` auf den eigenen Eventtyp reagieren. Während des beobachteten Turns veröffentlichte eigene Events werden vom SDK weitergereicht.

Browserrig nutzt diesen Mechanismus bereits für Browser- und Input-Events. Neue Capture-, Readiness- oder Figma-Plugins folgen demselben Muster. Die Entscheidung zwischen dauerhaft und transient beschreibt die Persistenz; beide Varianten können im Stream erscheinen. Dafür sind weder Ausgabeprofile noch eine zusätzliche Filter- oder Projektionsschicht vorgesehen.

Für neue Readiness-Ereignisse sollten `stage=initial|ongoing` und der konkrete Anlass sichtbar sein. Beide Stufen dürfen dieselbe Eventfamilie verwenden. `readiness_id`, Dokumentbezug, optional `action_id`, Start und genau ein terminales Ergebnis machen sie korrelierbar. Ein Poll-Tick ist Diagnose; ein Timeout oder Abbruch schließt den Vorgang. Bestehende gespeicherte Eventschemas benötigen bei Änderungen kompatible Defaults oder eine bewusste Versionierung.

Activity ist eine abgeleitete UI-Sicht. Der UI-Consumer sollte nicht versehentlich Readiness- und Activity-Ereignisse als zwei unabhängige Wartevorgänge darstellen. Ein fehlgeschlagener Readiness-Check nach einer bereits ausgeführten Aktion darf auch in der Darstellung keinen erneuten Klick nahelegen.

## 8. So könnte die Komposition aussehen

**API-Skizze, nicht direkt ausführbar.** `Agent`, `LaunchBrowser` und mehrere bestehende Plugins existieren; die neuen Parameter und Strategien zeigen die gewünschte Entwicklererfahrung.

```python
agent = Agent(
    model=model,
    plugins=[
        Chrome(LaunchBrowser(url=url)),
        Readiness(
            initial=FigmaLoaded(timeout=30),
            ongoing=VisualSettled(timeout=2),
        ),
        Observe(
            capture=CanvasCapture(region=FigmaViewport()),
            renderer=FigmaRenderer(),
            screenshots=Screenshots(
                trigger=ScreenshotTrigger.EACH_STEP,
            ),
        ),
        ImageContext(keep_latest_n_screenshots=3),
        Actions(chain_policy=ObserveAfterInput()),
        PointerTools(),
        KeyboardTools(),
        NavigationTools(),
        TabTools(),
        Activity(),
        LatestObservationOnly(),
    ],
)
```

Ein DOM-Agent verwendet stattdessen DOM-Capture, DOM-Renderer, DOM-Tools und Screenshots auf Anfrage. Ein hybrider Agent kombiniert DOM-Capture mit Canvas-Bildern und beiden Werkzeuggruppen. Reine Textbeobachtung benötigt keinen Bildkontext. Ein Figma-Rezept bündelt seine Auswahl in `figma_plugins(...)`; jedes zurückgegebene Element bleibt inspizierbar.

`BrowserAgent` kann als bequeme Fassade bestehen bleiben. Sie sollte ein explizites Rezept akzeptieren, statt immer zuerst den vollständigen Standardbrowser zu installieren und eigene Plugins nur anzuhängen. Zwei gleichzeitig im selben Scope montierte Browser-Stacks sind nochmals ein anderer Anwendungsfall: Die heutigen globalen Servicekeys und Toolnamen reichen dafür nicht. Zunächst separate Sessions verwenden; echte Mehrbrowser-Komposition braucht adressierte Services, Tools und Eventquellen.

## 9. Überschaubare Umsetzungsschritte

1. **Gemeinsame Verträge festlegen:** Strukturierte Beobachtung, Fähigkeiten und Bildbezug definieren. Aktueller Text-/DOM-Snapshot, zuletzt gezeigtes Bild und Bildhistorie sind getrennte Zustände mit expliziter Zuordnung.
2. **Readiness öffnen:** Initial- und laufende Policy injizierbar machen, gemeinsame Wait-Mechanik behalten. Dokumentbezogene Initialisierung einschließlich Dateivorschauen und ihrer Events definieren.
3. **Beobachtung öffnen:** Bestehende interne Capture-Strategien als gezielte Erweiterungspunkte zugänglich machen und Renderer austauschbar machen; `Observe` und `Readiness` lesen nicht länger unabhängig konfigurierte Modi. Gemeinsame Datentypen und Dokumentwechsel-Prüfungen erhalten.
4. **Screenshot-Aufnahme und Bildkontext trennen:** `Screenshots(trigger=...)` und `ImageContext(keep_latest_n_screenshots=...)` auf den vereinbarten Bildverträgen umsetzen. Insbesondere `ON_REQUEST` mit neuen Textbeobachtungen und unverändertem Bildpuffer prüfen.
5. **Tools nach Fähigkeiten montieren:** DOM-Werkzeuge von Pointer-/Fokuswerkzeugen trennen. Lokale Dateiwerkzeuge und Uploads explizit auswählbar machen. Dynamische Verfügbarkeitsprüfungen, Upload-Pfadvalidierung, Inputcontroller, Transaktionen und Fehlerbehandlung erhalten.
6. **Rezepte bereitstellen:** DOM, visuell, hybrid und Figma als flache Listen. Alte `DomMode`-/`CanvasMode`-Aufrufe zunächst in diese Rezepte übersetzen. Lokale Browserrig-Dateiwerkzeuge bei alternativen Harnessed-Dateiwerkzeugen gezielt weglassen können.
7. **Native Event-Erweiterung nutzen:** Eigene Eventtypen in den jeweiligen Plugins deklarieren und über Harnessed veröffentlichen. Die Weitergabe eigener dauerhafter und transienter Events im bestehenden Stream verifizieren.

Gezielt zu verifizieren sind: eigene Capture-/Renderer-Implementierung ohne Kernänderung; Initialisierung pro Dokument einschließlich SPA-Invalidierung; keine Wiederholung einer ausgeführten Aktion nach Settle-Fehler; korrekter Dokumentbezug von Screenshots nach Navigation; Session-isolierte Bildpuffer; korrekte Bildkoordinaten; tatsächliche Toolregistrierung pro Rezept; sowie die native Weitergabe eigener dauerhafter und transienter Events einschließlich Cancellation und normalem Turn-Ende.

Der bestehende Test `test_facade_registers_the_same_tool_plugins_in_every_mode` beschreibt die heutige Architekturentscheidung. Bei echter Fähigkeitskomposition muss er durch Erwartungen an die jeweiligen Rezepte ersetzt werden.

## 10. Präzisierungen nach erneuter Codeprüfung

**B bleibt die gewählte Architektur. Ein Umbau von Harnessed ist dafür nicht erforderlich.** Die neueren Änderungen präzisieren die Grenzen und die Reihenfolge der Umsetzung:

- **Dateifähigkeiten explizit komponieren.** Dokumentleser, Vorschauen und Uploads sind inzwischen umfangreicher. Rezepte müssen lokale Dateiwerkzeuge und Uploads bewusst einschließen oder weglassen können. Harnessed-Sandbox-Dateiwerkzeuge ersetzen Browserrigs lokale Dateizugriffe nicht automatisch; doppelte Toolnamen und ungewollt parallel angebotene lokale Zugriffe sind bei der Zusammenstellung zu vermeiden. Die vorhandenen Reader und ihre Formatregistrierung bleiben normale Python-Komponenten, keine zusätzlichen Harnessed-Plugins pro Dateiformat.
- **Statische Fähigkeiten und dynamische Verfügbarkeit getrennt behandeln.** Ohne DOM-Fähigkeit werden keine DOM-Tools installiert. Ein grundsätzlich installiertes Upload-Tool benötigt weiterhin zur Laufzeit ein gemeinsames Dateisystem. Die neue Validierung der vollständigen Dateiauswahl vor Browserinput sowie die Verfügbarkeitsprüfung bereits geplanter Toolaufrufe bleiben erhalten.
- **Bildbezug vor dem Herauslösen von `ImageContext` festlegen.** Bei `ON_REQUEST` kann eine neue Text-/DOM-Beobachtung entstehen, ohne dass ein neues Bild aufgenommen wird. Eine weiterhin im Modellkontext sichtbare Aufnahme behält deshalb ihre eigene Bild-ID, Aufnahmezeit, Tab-/Dokument-ID und Geometrie. Ein neuer Snapshot ohne Bild darf diese Geometrie nicht stillschweigend durch Viewport-Koordinaten ersetzen. Der Vertrag definiert explizit, welches Bild noch als Aktionsgrundlage gilt und wann nach Navigation, Tabwechsel oder relevanter Geometrieänderung eine neue Aufnahme erforderlich ist. Historische Vergleichsbilder sind nicht automatisch für Eingaben gültig.
- **Readiness für Dateivorschauen mitplanen.** Die Initialisierung gilt für das jeweilige Dokument. App-spezifische Strategien wie `FigmaLoaded` werden nicht unverändert auf ein geöffnetes PDF oder eine andere Vorschau angewandt. Dieses Verhalten gehört in die erste Umsetzung und ihre Tests.
- **Vorhandene Strategien öffnen, gemeinsame Mechanik erhalten.** Capture und Readiness besitzen bereits interne Strategien. Diese werden gezielt zugänglich gemacht. Gemeinsame Transaktionen, Cancellation, Fehlerbehandlung und Dokumentwechsel-Prüfungen bleiben zentral. Neue Schnittstellen betreffen Browserrig; Harnessed übernimmt weiterhin Zusammensetzung, Lifecycle und Eventauslieferung.

Die Screenshot-API bleibt unverändert klein: `Screenshots(trigger=ScreenshotTrigger.EACH_STEP)` beziehungsweise `ON_REQUEST` und `ImageContext(keep_latest_n_screenshots=N)`. Zusätzliche Serien-, Intervall- oder Auswahloptionen sind nicht vorgesehen.

Validierungsstand der erneuten Prüfung: **43 Tests bestanden** aus `tests/test_composition.py`, `tests/test_dependencies.py`, `tests/test_actions.py` und `tests/test_readiness.py` mit Harnessed 0.6.0. Der erste Lauf scheiterte bei Temp-Verzeichnis-Fixtures an Zugriffsrechten; mit einem eigenen Test-Temp-Verzeichnis im Workspace bestand der vollständige ausgewählte Lauf. Das bestätigt die geprüfte Ausgangsbasis, nicht die noch ausstehende Implementierung von B; ein vollständiger Integrationslauf war nicht Teil dieser Prüfung.

## Quellen der Prüfung

Browserrig: die oben verlinkten Dateien sowie [`agent.py`](browserrig/agent.py), [`observation/models.py`](browserrig/observation/models.py), [`readiness/plugin.py`](browserrig/readiness/plugin.py), [`readiness/dom.py`](browserrig/readiness/dom.py), [`readiness/canvas.py`](browserrig/readiness/canvas.py), [`events.py`](browserrig/events.py), [`browser/plugin.py`](browserrig/browser/plugin.py), [`activity/plugin.py`](browserrig/activity/plugin.py), [`terminal.py`](browserrig/terminal.py) und [`tests/test_composition.py`](tests/test_composition.py).

Ursprüngliche Prüfung mit Harnessed 0.5.0, direkt im installierten Quellcode unter `.venv/Lib/site-packages/harnessed/`: `agent.py`, `core/plugin.py`, `kernel/declarations.py`, `kernel/plugin.py`, `kernel/keys.py`, `core/messages.py`, `plugins/observations.py`, `core/prompt/values.py`, `core/runtime/session.py`, `core/runtime/streaming.py`, `core/stream.py`, `core/event_registry.py` und `events/__init__.py`.

Nach dem Upgrade auf Harnessed 0.6.0 erneut geprüft: installierter Versionsstand, `agent.py`, `core/plugin.py`, die textbasierte `Observation` in `core/messages.py` und die Weitergabe eigener Eventtypen in `core/runtime/streaming.py`. Die oben genannten 43 Tests ergänzen diese Quellcodeprüfung. Weitere Browserrig-Quellen für die Präzisierungen: [`tools/files.py`](browserrig/tools/files.py), [`files/system.py`](browserrig/files/system.py), [`files/formats.py`](browserrig/files/formats.py), [`files/reading.py`](browserrig/files/reading.py), [`tests/test_actions.py`](tests/test_actions.py) und [`tests/test_dependencies.py`](tests/test_dependencies.py).
