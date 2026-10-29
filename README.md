# Browserrig

Browserautomation mit Harnessed, cdpify und Pydantic. Ein Browser-Seam,
fest adressierte Tabs, explizite DOM-/Canvas-Modi und ein gemeinsames Event-Log.
Die Quellen liegen direkt in `browserrig/`.

```powershell
uv sync --extra openai
Copy-Item .env.example .env
# OPENAI_API_KEY in .env eintragen.
uv run --env-file .env --extra openai python -m examples.openai_agent --headed --record
```

Die Beispielmission erkundet das Voyager-Programm: Missionen vergleichen,
Detailartikel in neuen Tabs öffnen und ungewöhnliche Inhalte der Golden Record
finden. `--task` und `--url` überschreiben Aufgabe und Startseite.

Die Beispiele verwenden `OpenAIResponsesModel` und standardmäßig `gpt-6.1-terra`.
`OPENAI_MODEL` überschreibt die Modell-ID. Für Tool Calling wird die
[Responses API benötigt](https://developers.openai.com/api/docs/models/gpt-6.1-terra).
Die Tests verwenden geskriptete Modelle und benötigen keinen API-Key.

## Direkt ohne LLM

```python
from browserrig import ChromeBrowser, LaunchBrowser, wait_for_page

async with ChromeBrowser(LaunchBrowser(url="https://example.com")) as browser:
    tab = browser.active_tab
    await wait_for_page(browser, tab)
    print(await tab.evaluate("document.title"))
```

```powershell
uv run python -m examples.direct_browser --url https://example.com
uv run python -m examples.connect_browser --endpoint http://127.0.0.1:9222
```

Connect öffnet einen eigenen isolierten Kontext im laufenden Browser.
`--target-id TARGET` wählt ausdrücklich einen vorhandenen Tab. Der externe
Browser bleibt beim Disconnect erhalten und muss CDP bereits anbieten.

## Mit Harnessed komponieren

```python
from harnessed import Agent, PolicyDecision
from harnessed.models import PydanticAIModel
from harnessed.plugins import Approvals
from pydantic_ai.models.openai import OpenAIResponsesModel
from browserrig import WebMode, LaunchBrowser, RecordingOptions, browser_plugins

async with OpenAIResponsesModel("gpt-6.1-terra") as openai:
    agent = Agent(
        model=PydanticAIModel(openai),
        plugins=[
            *browser_plugins(
                LaunchBrowser(url="https://de.wikipedia.org/wiki/Voyager-Programm"),
                mode=WebMode(screenshots=True),
                recording=RecordingOptions(),
            ),
            Approvals(default=PolicyDecision.ALLOW),
        ],
    )
    result = await agent.run("Vergleiche Voyager 1 und 2 mit Quellen-URLs.", max_steps=20)
    print(result.text)
```

`browser_plugins()` gibt eine normale, inspizierbare Plugin-Liste zurück.
Eigene Komposition: `Chrome`, `Readiness`, `Observe`, `Actions`, gewünschte
Tool-Plugins, `Nudges`, `Activity` und optional `Recording`.

## Controls und Canvas

```python
handle = await session.submit("Untersuche diese Seite.")
await session.pause()
await session.steer("Konzentriere dich auf die Navigation.")
await session.context.set("constraints", "Keine Formulare absenden.")
await session.resume()
result = await handle.result()
```

Pause wartet auf die vollständige Schrittgrenze und friert Chromium nicht ein.
`session.stop()` beendet geordnet, `session.abort()` unterbricht unmittelbar.
Resume beobachtet die aktuelle Seite neu. Activity verwendet Events, keinen LLM-Decorator.

```powershell
uv run --env-file .env --extra openai python -m examples.controls
uv run --env-file .env --extra openai python -m examples.figma_agent --url YOUR_URL --record
```

Canvas verwendet Bild und Koordinaten. Die Initialprüfung prüft Geometrie und
Pixelinhalt. DOM-Modus liefert Pydantic-validiertes YAML mit Rollen, Labels und
beobachtungsgebundenen Referenzen.

## Aufnahme, Downloads und Events

Native Aufnahme verwendet `Page.startScreenRecording`/`stopScreenRecording` über
cdpify. Unter `.browserrig/recordings/` liegen Segmente und ein validiertes Manifest
mit Prüfsummen, Zeitbezügen und Abschnitten ausschließlicher Modellwartezeit.
Der Container wird geprüft; ffmpeg ist keine Laufzeitabhängigkeit.
Canvas-Crop und native Viewportaufnahme sind im Manifest unterscheidbar.

`LaunchBrowser(download_directory="ABSOLUTE_PATH_ON_BROWSER_HOST")` aktiviert
Downloads im eigenen Kontext. `DownloadState` enthält `IN_PROGRESS`, `COMPLETED`
und `CANCELED`; die Events liegen unter `browser.download.*`.
Upload- und Downloadpfade beziehen sich auf den Browserhost.

```python
from browserrig.events import ActionStartedEvent

async for event in session.subscribe():
    match event:
        case ActionStartedEvent(kind=kind):
            print(kind)
```

## Entwicklung und Arbeitsstand

Python >=3.12, uv und Node.js >=24 werden für die Entwicklungswerkzeuge benötigt.

```powershell
uv sync --locked --extra openai
npm.cmd ci
uv run pre-commit install
uv run pre-commit run --all-files

uv run ruff check browserrig examples tests
uv run ruff format --check browserrig examples tests
uv run pylint browserrig examples tests
uv run ty check
npm.cmd run lint
npm.cmd run format:check
uv run pytest -m "not integration"
uv run pytest -m integration
uv build
```

Die Pre-commit-Hooks verwenden die in den Lockfiles festgelegten uv-/npm-Abhängigkeiten.
Unter Linux/macOS heißt der npm-Aufruf `npm`. JavaScript wird mit ESLint und Prettier
geprüft: geschweifte Klammern für alle Kontrollblöcke, maximal zwei verschachtelte
Blöcke und keine verschachtelten ternären Ausdrücke. Pylint begrenzt verschachtelte
Python-Blöcke auf drei; Ruff prüft zusätzlich Vereinfachungen. CI führt dieselben
Lint-, Format- und Typprüfungen aus. Zum Formatieren: `uv run ruff format browserrig examples tests`
und `npm.cmd run format`.

Integrationstests benötigen Chrome/Chromium. `BROWSERRIG_CHROME` oder
`LaunchBrowser(executable=...)` kann das Binary vorgeben. Medienprüfung verwendet
zusätzlich ffprobe, wenn vorhanden.

Der Kern ist implementiert und gegen echtes Chrome geprüft. Breite Plattformmatrix,
komplexe Figma-Geräterahmenerkennung, transformierte/OOPIF-Frames und Prozesscrash-
Recovery bleiben gezielte Abnahmebereiche. Verträge stehen in [SPEC.md](SPEC.md),
Zuständigkeiten in [STRUTURE.md](STRUTURE.md).
