# Browserrig-Steering: Vizron-Referenz und offene Arbeiten

Diese Notizen enthalten die anwendungsspezifische Auswertung von `../vizron` und
Vorschläge für Browserrig. Sie sind vom fachlichen
[Harnessed-Feedback](harnessed-feedback.md) und den generischen
[API-Proposals](harnessed-api-proposals.md) getrennt. Es wird hier kein
Browserrig-Code implementiert.

## Was Vizron tatsächlich macht

Vizron unterscheidet eine feste Tool-Eigenschaft und einen fallabhängigen Abbruch.
Die untersuchten Quelltexte bestätigen den folgenden Ablauf:

1. **Feste Metadaten:**
   [BrowserToolMetadata](../vizron/src/vizron/tools/metadata.py) enthält
   `chainable: bool = False`. Das ist die Voreinstellung in Vizron. Navigation,
   Suche und Zurück verwenden diese nicht verkettbare Voreinstellung.
2. **Ausführung vor Abbruch:**
   [ActionChainMiddleware](../vizron/src/vizron/tools/middleware/action_chain_middleware.py)
   führt zuerst das aktuelle Tool aus. Danach setzt sie bei `chainable=False`
   dessen Ergebnis auf `break_action_chain=True`. Das aktuelle Tool wird also
   nicht verworfen; nur danach endet die Kette.
3. **Sequenzielle Kette:**
   [ActionExecutor](../vizron/src/vizron/agent/action_executor.py) arbeitet die
   Tool-Aufrufe einer Modellantwort in Reihenfolge ab. Nach jedem Ergebnis kann
   die Schleife abbrechen. Es geht um mehrere Aufrufe aus demselben Modell-Roundtrip.
4. **Zusätzlicher Navigationsschutz:** Derselbe Executor vergleicht nach jedem
   ausgeführten Aufruf die Navigationsrevision mit dem Stand vor der Kette.
   Erkannte Navigation beendet sie auch dann, wenn das Tool grundsätzlich
   verkettbar war. Beispielsweise ist der DOM-Klick in Vizron `chainable=True`,
   kann aber trotzdem eine Navigation auslösen.
5. **Dynamische Unterbrechung:**
   [MouseTools](../vizron/src/vizron/tools/defaults/mouse.py) stellen einen Klick
   zurück, wenn beim Hover relevante neue Elemente erkannt wurden.
   [KeyboardTools](../vizron/src/vizron/tools/defaults/keyboard.py) können nach
   dem Tippen bei Vorschlägen oder einem nicht korrigierten Tippfehler abbrechen.
   Dafür gibt es `ActionResult.break_action_chain`, unabhängig von der statischen
   Tool-Eigenschaft. Ein Fehler setzt diesen Wert ebenfalls.
6. **Antworten auf übersprungene Calls:**
   [MessageManager](../vizron/src/vizron/agent/messages/messages.py) ergänzt für
   nicht ausgeführte Calls eine Antwort mit dem Hinweis, dass die Aktionskette
   gestoppt oder das Aktionslimit erreicht wurde.

Der zentrale Middleware-Ausschnitt lautet im vorhandenen Vizron-Code:

```python
result = await next(call)
if call.tool is None or not browser_metadata(call.tool).chainable:
    result.break_action_chain = True
return result
```

Das Verhalten ist unter anderem in
[test_action_chain_middleware.py](../vizron/tests/vizron/tools/middleware/test_action_chain_middleware.py),
[test_tools.py](../vizron/tests/vizron/tools/test_tools.py) und
[test_action_executor_native.py](../vizron/tests/vizron/agent/test_action_executor_native.py)
beschrieben. Diese Aussage beruht auf Quelltextprüfung; die Vizron-Tests wurden
für diese Dokumentation nicht ausgeführt.

Vizron liest seine Erweiterung über
`tool.metadata.get(BrowserToolMetadata)`. Dieser Verbraucher-Vertrag ist ein
passendes Vorbild für allgemeinen Metadatenzugriff in Harnessed. Die Browserfelder
selbst gehören zur Anwendung.

## Beispiel einer Kette mit Navigation

```text
Vom Modell geplant: Feld A ausfüllen → navigieren → altes Element klicken
Tatsächlich:         Feld A ausfüllen → navigieren → Kette beendet
Übersprungen:                                       altes Element klicken
Danach: neue Beobachtung und neue Modellentscheidung
```

Das Navigationstool trägt eine feste Grenze. Bei einem grundsätzlich verkettbaren
Klick, der tatsächlich navigiert, muss Browserrig die Kontextänderung erkennen
und zusätzlich den dynamischen Abbruch melden. Harnessed braucht für beide Fälle
nur den generischen Ausführungsvertrag, keine Kenntnis von Seiten oder Elementen.

## Beispiel für anwendungseigene Tool-Metadaten

Die folgende API-Skizze verwendet die separat vorgeschlagenen Harnessed-Verträge.
`BrowserAction` bleibt eine Browserrig-eigene Dataclass; `ChainPolicy` gehört zum
allgemeinen Ausführungsvertrag des SDK.

```python
from dataclasses import dataclass

from harnessed import ToolResult, tool
from harnessed.tools import ChainPolicy

from browserrig.core.kinds import ActionKind


@dataclass(frozen=True, slots=True)
class BrowserAction:
    kind: ActionKind
    expects_change: bool = False


@tool(
    metadata=(
        ChainPolicy(chainable=False),
        BrowserAction(kind=ActionKind.NAVIGATE),
    ),
)
async def navigate(url: str) -> ToolResult: ...
```

Browserrig kann seine eigenen Angaben in Plugins auswerten. Harnessed muss dafür
weder `BrowserAction` noch `ActionKind.NAVIGATE` kennen.

Vizrons Default `chainable=False` ist eine eigene konservative Entscheidung.
Der technische Harnessed-Vorschlag erhält für Tools ohne deklarierte Kettenregel
zunächst das bisherige Verhalten. Der Default muss also nicht unverändert aus
Vizron übernommen werden; die Bedeutung einer deklarierten Grenze bleibt gleich.

## Zuständigkeiten

| Thema                                                                                | Zuständigkeit               | Begründung                                                                     |
| ------------------------------------------------------------------------------------ | --------------------------- | ------------------------------------------------------------------------------ |
| Neue Vorschläge, Menüs oder Overlays nach Tippen/Hover erkennen                      | Browserrig                  | Dafür braucht man Browserzustand und die Bedeutung der Interaktion.            |
| Restliche Tool-Aufrufe einer Modellantwort unterbrechen                              | Harnessed                   | Der Executor besitzt Reihenfolge, Scheduling, Approvals und Ergebniszuordnung. |
| Statisch festlegen, nach welchem Tool eine neue Modellentscheidung nötig ist         | Harnessed                   | Das sind Ausführungsmetadaten eines Tools, unabhängig vom Browser.             |
| Wiederholte Aktionen ohne beobachtbaren Fortschritt erkennen und einen Nudge liefern | Browserrig                  | Fortschritt hängt von Seite, Ziel, Downloads, Dialogen und Aktion ab.          |
| Aufgelöstes Schrittlimit öffentlich an Hooks liefern                                 | Harnessed                   | Der Runtime sind Agent-Konfiguration und Turn-Overrides bekannt.               |
| Letzten verfügbaren Schritt für eine Zusammenfassung reservieren                     | Harnessed                   | Das betrifft Loop, Limits, Ausführungsschutz und strukturierte Ausgaben.       |
| Persona, Think-aloud, emotionales Usability-Steering                                 | Optionales Anwendungsplugin | Gehört zum Testformat und nicht zum allgemeinen Ausführungsvertrag.            |

## Vorgeschlagenes Verhalten in Browserrig

| Aktion/Situation                                | Vorgeschlagenes Browserrig-Verhalten                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------- |
| Normales Füllen mehrerer Felder                 | Verkettbar, solange keine relevante neue Entscheidung entsteht.                       |
| Tippen öffnet relevante Vorschläge              | Eingegebenen Text bestätigen, `break_chain=True`, nachfolgende Aktionen überspringen. |
| Hover öffnet ein relevantes Menü/Overlay        | Ursprünglichen Klick zurückstellen, dies ausdrücklich melden, `break_chain=True`.     |
| Navigation oder Wechsel des aktiven Tabs        | Konservative statische Grenze mit `ChainPolicy(chainable=False)`.                     |
| Scrollen oder Koordinatenaktionen               | Zunächst ebenfalls eine neue Modellentscheidung verlangen.                            |
| DOM-Klick                                       | Kann verkettbar sein; erkannte Navigation beendet die Kette zusätzlich.               |
| Textticker, Animation oder kosmetische Mutation | Keine pauschale Unterbrechung.                                                        |

Die Erkennung bleibt vollständig in Browserrig. Sie sollte stabile DOM-Identität
und relevante Bedienelemente vergleichen, keine wechselnden Beobachtungs-Refs.
Eine interne Vergleichsprobe darf die weiterhin gültige Ref-Zuordnung nicht
überschreiben. Auch unverändert vorhandene, erst sichtbar gewordene Menüs können
eine neue Entscheidung darstellen; bloß neue DOM-Knoten zu zählen reicht nicht.

## Wiederholungs-Nudge in Browserrig

Hier ist zunächst **kein neuer Harnessed-Kernmechanismus** nötig. Browserrig hat
bereits eine Nudge-Queue mit Ursache, Browser-/Tab-/Dokumentbezug, begrenzter
Auslieferung und Bestätigung über `ObservationsIncludedEvent`.

Ein zusätzlicher Detektor sollte folgende Evidenz zusammenführen:

- Wiederholte, vergleichbare Aktionen auf demselben tatsächlichen Ziel mit
  vergleichbaren Argumenten und demselben Seitenkontext.
- Danach weiterhin derselbe beobachtbare Zustand beziehungsweise wiederholt
  derselbe konkrete Fehler, statt eines pauschalen Vergleichs aller Fehlertexte.
- Ausbleibende zusätzliche Effekte wie Download, neuer Tab oder Dialog.
- Zurücksetzen oder getrenntes Fortschreiben bei beobachtbarem Fortschritt,
  verändertem Ziel, neuem Turn oder gewechseltem Dokument.

Neue Ref-IDs sind kein Strategiewechsel. Identische Labels allein beweisen
umgekehrt nicht, dass es dasselbe Ziel war. Wiederholtes `read_file`, Beobachten
oder bewusstes Warten ist nicht automatisch ein erfolgloser Mutationsversuch.
Signaturen sollen keine Passwörter oder vollständigen Eingabetexte ins Log kopieren.

Vorgeschlagener modellseitiger Hinweis, beispielhaft ab drei vergleichbaren
Versuchen ohne beobachtbare Änderung:

> The same action has produced no observable change in three attempts. Inspect
> the current state and change the target or approach before retrying.

Der Hinweis informiert und fordert einen Strategiewechsel an. Er beendet den
Turn nicht und setzt eine beobachtete Zustandsänderung nicht mit Task-Erfolg gleich.
Schwelle und Wiederholungsfenster sollten konfigurierbar und die Zustände begrenzt
sein. Kurze wiederkehrende Muster wie `A → B → A → B` wären eine spätere Erweiterung;
sie sollten nicht als bereits vorhandene allgemeine Loop-Erkennung beworben werden.

Browserrig braucht später eigene Verhaltenstests für Hover, Vorschlagslisten,
unveränderte Feldketten, irrelevante Mutationen und die Wiederholungs-Nudges.
Diese Browserfälle gehören nicht in die generischen Harnessed-Tests.
