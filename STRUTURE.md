# Browserrig — Struktur

Die Python-Quellen liegen direkt unter `browserrig/browserrig`, ohne `src/`-Zwischenebene.
[Die Spezifikation](SPEC.md) beschreibt die Verträge; dieser Baum erklärt deren Platz.

```text
browserrig/
├── SPEC.md
├── STRUTURE.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .github/workflows/checks.yml
├── browserrig/
│   ├── __init__.py
│   ├── py.typed
│   ├── kinds.py
│   ├── events.py
│   ├── composition.py
│   ├── browser/
│   │   ├── base.py
│   │   ├── chrome.py
│   │   ├── plugin.py
│   │   ├── config.py
│   │   ├── tab.py
│   │   ├── process.py
│   │   ├── models.py
│   │   ├── images.py
│   │   └── errors.py
│   ├── readiness/
│   │   ├── plugin.py
│   │   ├── wait.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── dom.py
│   │   ├── figma.py
│   │   └── scripts/
│   │       ├── dom.js
│   │       └── canvas.js
│   ├── observation/
│   │   ├── plugin.py
│   │   ├── config.py
│   │   ├── capture.py
│   │   ├── models.py
│   │   ├── render.py
│   │   └── scripts/
│   │       ├── snapshot.js
│   │       └── element.js
│   ├── tools/
│   │   ├── execution.py
│   │   ├── navigation.py
│   │   ├── interaction.py
│   │   ├── gestures.py
│   │   ├── forms.py
│   │   ├── tabs.py
│   │   ├── files.py
│   │   └── dialogs.py
│   ├── nudges/
│   │   └── plugin.py
│   ├── recording/
│   │   ├── plugin.py
│   │   ├── config.py
│   │   └── models.py
│   └── activity/
│       ├── plugin.py
│       └── models.py
├── examples/
│   ├── direct_browser.py
│   ├── connect_browser.py
│   ├── openai_agent.py
│   ├── controls.py
│   └── figma_agent.py
└── tests/
    ├── conftest.py
    ├── fakes.py
    ├── test_events.py
    ├── test_readiness.py
    ├── test_nudges.py
    ├── test_browser_integration.py
    ├── test_agent_integration.py
    ├── test_controls_integration.py
    └── test_recording_integration.py
```

`__init__.py`-Dateien in den Fähigkeitspaketen exportieren nur deren kleine API.
Der Baum wird mit tatsächlich notwendigen Modulen erweitert, nicht durch leere
Platzhalter für eine theoretische Architektur.

## Gemeinsame Verträge

`kinds.py` enthält geschlossene Werte, die mehrere Fähigkeiten und Eventverträge
teilen, etwa `ActionKind` und `ActivityKind`. Fähigkeitslokale Enums wie
`BrowserKind` bleiben bei der betreffenden Konfiguration.

`events.py` ist der öffentliche Katalog unveränderlicher Harnessed-Records.
Klassen heißen beispielsweise `ActionStartedEvent`; ihre Tags verwenden
`EventKind.ACTION_STARTED` mit dem Wire-Wert `browser.action.started`.
Die direkte Importform benötigt keinen Namespacepräfix an jeder Hook-Deklaration.

`composition.py` liefert lediglich eine sichtbare Liste realer Plugins.
Es registriert keine zweite Toolregistry und enthält keinen Agentenloop.

## Browser

| Datei | Verantwortung |
| --- | --- |
| `base.py` | der einzige Browser-Seam `Browser` und der schmale Event-Sink |
| `chrome.py` | Verbindung, Kontexte, Target-/Session-Routing und Ressourcenbesitz |
| `plugin.py` | Chrome öffnen, als Browser bereitstellen und scoped Cleanup besitzen |
| `config.py` | Launch-/Connect-Union, BrowserKind, Viewport und Validierung |
| `tab.py` | fest adressierter Tab und interne CDP-Frames/isolierte JS-Kontexte |
| `process.py` | privates Binary-Resolving, temporäres Profil, Start und Prozessende |
| `images.py` | Capture, Pixelproben und Bildoperationen ohne Prompt-/Readiness-Policy |
| `models.py` | Geometrie, Tab- und Downloadansichten |
| `errors.py` | konkrete Browserfehler |

Ein `Frame` ist ein Browser-/CDP-Objekt, keine weitere Service-Fassade.
Seine Kontext-ID entscheidet, in welchem Hauptdokument oder iframe JavaScript läuft.
Tastatur und Maus werden auf der Session des gebundenen Tabs ausgelöst.

## Readiness

`wait.py` enthält den fachlichen Ablauf und wird auch ohne Agent direkt verwendet.
`plugin.py` besitzt nur scoped Cache, geteilte Tasks und Harnessed-Lifecycle.

`dom.py` und `figma.py` liefern passende validierte Probes. Es gibt keinen
zusätzlichen `ReadinessController` zwischen Plugin und fachlicher Logik.

`models.py` definiert Report, Status und Phase. `scripts/` enthält kleine isolierte
Browserprobes und wird als Paketressource ausgeliefert.

## Observation

`capture.py` validiert Extraktion und Browserfakten, bindet Referenzen und
berechnet den typisierten Fingerprint. Die Extraktion in `snapshot.js` bleibt
als nachvollziehbare Sammlung von Sichtbarkeit, Labels, Rollen und Werten lesbar.

`models.py` enthält Snapshot, Extraktionsergebnis und Fingerprint-Eingaben.
`render.py` enthält Pydantic-Ansichtsmodelle und deren YAML-Serialisierung.

`plugin.py` koordiniert vor dem Modellschritt:
Readiness → Capture → Ereignisse/Regeln → Nudge-Projektion → Harnessed-Observation.
Der `PrepareRequest`-Hook ergänzt im visuellen Modus ein natives Bild.

## Tools und die Aktionsgrenze

`execution.py` enthält `Actions`, den Besitzer einer Browseraktion.
Tools injizieren diese Fähigkeit und rufen `actions.run(kind=..., operation=...)` auf.
Serialisierung, Readiness und Ergebnisereignisse werden dort zusammengehalten.

Die fachlichen Module besitzen die tatsächlichen `@tool`-Methoden. Sie registrieren
keinen eigenen Middleware-Stack. Dialogbehandlung hängt direkt am Browser,
damit sie ein blockiertes Readiness-Gate auflösen kann.

`gestures.py` enthält native Klick-/Doppelklick- und Drag-Sequenzen einschließlich
HTML5-DataTransfer und Cancellation-Cleanup. Die Tools besitzen die Schemas;
die Gestenfunktionen besitzen keine zusätzliche Agenten- oder Plugin-Laufzeit.

`PointerTools` bietet Koordinaten/Keys/Scrollen. `InteractionTools` ergänzt den
DOM-Referenzklick. Die Moduskomposition entscheidet explizit über das Angebot.

## Nudges

Die kleine Fähigkeit beginnt in einer Datei. Sie enthält State, Replay mit
`match/case`, Deduplizierung, Gültigkeit und die wenigen konkreten Regeln.
Eine Aufteilung in zusätzliche Regelmodule erfolgt erst bei tatsächlichem Bedarf.

Hinweise reagieren auf Events und projizieren Daten. Sie steuern weder das LLM
noch Controls und lösen keine zusätzlichen Turns aus.

## Recording und Activity

`recording/plugin.py` besitzt native Aufnahme, begrenzte IO-Übernahme, Segmente
und Cleanup. Es gibt keinen obligatorischen Encoderprozess und keine JPEG-Pipeline.
`recording/models.py` definiert das Pydantic-Manifest und seine Segmente.

`activity/plugin.py` liest vorhandene Modell-/Tool-/Control-Ereignisse.
`activity/models.py` enthält Zeitbereiche und die reine Überlappungsprojektion.
`ActivityKind` wird im Event und in der Berechnung gemeinsam verwendet.

Das LLM bleibt das native Modell plus Harnesseds vorhandener Provideradapter.

## Tests, Beispiele und Qualitätsgrenzen

Offline-Tests prüfen Codec, Scope-Isolation, Readiness und Nudge-Ursachen.
Integrationstests verwenden echtes Chrome, lokale HTML-Seiten und geskriptete
Modelle. Sie prüfen das Zusammenspiel statt eine Modellantwort vorherzusagen.

Die CI führt Lint, Typprüfung, Tests und einen Wheel-Smoke-Test aus.
OpenAI-Beispiele werden auf Imports/Konfiguration geprüft; echte API-Aufrufe
bleiben explizite Benutzeraktionen.

`examples/` zeigt direkten Browserzugriff, Attach, OpenAI Responses, Controls
und Canvas. Das Agentenbeispiel kann native Aufnahme zusätzlich einschalten.

Offene Abnahmebereiche stehen in SPEC und README. Ordnernamen allein gelten
nicht als Nachweis vollständiger Produktionsreife.
