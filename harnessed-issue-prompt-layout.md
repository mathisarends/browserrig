# harnessed: Prompt-Layout deklarativ machen (Platzierung nach Typ, optionale Abschnitte, Kit-Layouts)

Gemessen an harnessed 0.9.0. Alle Aussagen zum Ist-Verhalten sind mit Skripten gegen 0.9.0 geprüft.

## Motivation

browserrig gibt ein festes Prompt-Layout vor: Rollentext, dann die Browser-Anweisungen in Lesereihenfolge, dann
die Anweisungen fremder Plugins, `Done` am Schluss, alles als Markdown. Mit 0.9.0 sieht die Facade so aus:

```python
kit = browser_kit(browser=browser)
kit = kit.without(*without)
plugins = [plugin for plugin in plugins if plugin is not None]
if not isinstance(system_prompt, SystemPrompt):
    system_prompt = SystemPrompt(
        *((system_prompt,) if system_prompt is not None else ()),
        browser_instructions(kit),
        PluginInstructions(),
        # Finishing is the last step, so its guidance closes the prompt.
        *(PluginInstructions(plugin) for plugin in plugins if isinstance(plugin, Done)),
        format=PromptFormat.MARKDOWN,
    )
super().__init__(model=model, system_prompt=system_prompt, plugins=[kit, *plugins], ...)
```

Dazu kommt im Kit:

```python
observe, images = Observe(), ImageContext()
actions, pointer = Actions(), PointerTools()
files = FileTools()
return Kit(..., plugins=[..., observe, images, actions, ..., pointer, ..., files, ...],
           fragments={"observation": (observe, images), "actions": (pointer, actions), "files": (files,)})

def browser_instructions(kit: Kit) -> SystemPrompt:
    return SystemPrompt(kit.fragment("observation"), kit.fragment("actions"), kit.fragment("files"))
```

Jede unschöne Stelle geht auf eine fehlende Fähigkeit in harnessed zurück:

| Stelle | Ursache in harnessed |
|---|---|
| `*((system_prompt,) if ... else ())` | `SystemPrompt` lehnt `None`-Teile ab (`TypeError`). |
| `*(PluginInstructions(p) for p in plugins if isinstance(p, Done))` | Platzierung geht nur über die Instanz. `PluginInstructions(Done)` und ein nicht installiertes `Done()` scheitern mit `ConfigError: PluginInstructions refers to an uninstalled plugin`. Ein `Done` aus einem Kit oder einem verschachtelten Kit findet die Facade so gar nicht. |
| `if not isinstance(system_prompt, SystemPrompt)` | Ein Kit kann kein bevorzugtes Layout und Format mitbringen. Jeder Nutzer des Kits muss das Layout nachbauen. |
| `observe, images = Observe(), ImageContext()` | Fragmente lassen sich nur mit Instanzen deklarieren, nicht nach Typ. |
| `browser_instructions(kit)` als eigene Funktion | Fragmente können nicht relativ zum Kit in einem Layout stehen, das das Kit selbst deklariert. |
| `trust` steht nach `refs`, obwohl er später besser passt | Fragmente arbeiten pro Plugin. Einzelne Abschnitte eines Plugins lassen sich nicht robust umsortieren (Details unter P4). |
| `plugins = [p for p in plugins if p is not None]` | `Agent(plugins=...)` überspringt `None` nicht. |

## Ziel: so soll die Facade aussehen

```python
# composition.py
def browser_kit(*, browser: BrowserOptions | None = None) -> Kit:
    return Kit(
        name="browserrig",
        plugins=[Activity(), Chrome(browser), ..., Observe(), ImageContext(), Actions(), ...,
                 PointerTools(), ..., FileTools(), ContextCompaction(trigger=WindowRatio())],
        prompt=SystemPrompt(
            PromptText(),                       # Platzhalter für den Rollentext des Aufrufers
            Observe.page_state, Observe.refs, ImageContext.usage,
            PointerTools.coordinates, Actions.chains,
            FileTools.usage,
            PluginInstructions(),               # alle übrigen Plugins (Secrets, Handoff, …)
            Observe.trust,
            PluginInstructions(Done, optional=True),
            format=PromptFormat.MARKDOWN,
        ),
    )

# agent.py
kit = browser_kit(browser=browser).without(*without)
super().__init__(
    model=model,
    system_prompt=kit.system_prompt(system_prompt),
    plugins=[kit, *plugins],
    plugin_validation=plugin_validation,
)
```

Damit entfallen `browser_instructions`, die Fragmente, die lokalen Instanz-Variablen, der `isinstance`-Zweig, das
Tupel-Entpacken und der Generator. Das Layout lebt einmal im Kit und gilt auch für Nutzer, die `browser_kit()`
direkt an `harnessed.Agent` geben.

## Vorschläge

Sortiert nach Nutzen pro Aufwand. P1 und P2 allein machen die Facade schon deutlich lesbarer.

### P1 – Platzierung nach Typ, optional

```python
PluginInstructions(Done)                  # der installierte Gewinner, der eine Done-Instanz ist
PluginInstructions(Done, optional=True)   # nichts, falls kein Done installiert ist
PluginInstructions(slot="completion")     # nach Slot statt Typ (optional, siehe offene Fragen)
```

Semantik:

- Ein Typ wird gegen die **finalen** Gewinner der Komposition aufgelöst (nach Kit-Ersetzungen und `without`), per
  `isinstance`. So zählt auch ein `Done` aus einem verschachtelten Kit, und ein Ersatz aus einer Unterklasse ebenso.
- Passen mehrere installierte Plugins: `ConfigError` mit den Namen der Kandidaten. Alternative: alle in
  Kompositionsreihenfolge platzieren. Fehler ist sicherer und lässt sich später lockern.
- Ohne `optional=True` ist ein fehlender Typ ein `ConfigError`, wie heute bei einer fremden Instanz.
- Das Ausschließen eines Plugins (`SystemPrompt(exclude=...)`) nimmt aus demselben Grund auch Typen an.
- Die Prüfung "placed or excluded twice" vergleicht aufgelöste Plugins. `PluginInstructions(done)` plus
  `PluginInstructions(Done)` ist also doppelt.

Dasselbe für einzelne Abschnitte:

- Heute liefert `Observe.trust` (ein statisches `Instructions` auf Klassenebene) die Deklaration selbst, und die
  Komposition ordnet sie über die Identität der Deklaration dem installierten `Observe` zu. Geprüft: der Abschnitt wird
  verschoben, nicht dupliziert. Das ist praktisch, aber nicht dokumentiert.
- `Observe.refs` (ein `@instructions`-Provider) liefert auf Klassenebene einen `InstructionProvider`, und
  `SystemPrompt` lehnt ihn ab (`TypeError: SystemPrompt sections must be strings, section references or groups`).
- Vorschlag: Klassen-Referenzen für beide Deklarationsarten offiziell machen. Sie werden nach
  `(Gewinner mit isinstance(owner_type), Attributname)` aufgelöst, nicht nach der Identität der Deklaration. Dann
  trifft die Referenz auch eine Unterklasse, die `trust` überschreibt. Mit `optional` gelten dieselben Regeln wie bei
  `PluginInstructions(Type)`.

Abnahme:

- `SystemPrompt(PluginInstructions(), PluginInstructions(Done))` rendert `Done.usage` zuletzt, egal ob `Done` direkt,
  über ein Kit oder über ein verschachteltes Kit kommt.
- `PluginInstructions(Done, optional=True)` ohne installiertes `Done` rendert ohne Fehler und ohne leeren Abschnitt.
- `PluginInstructions(Done)` ohne installiertes `Done` ergibt einen `ConfigError`, der den Typ nennt.
- Zwei installierte Plugins vom Typ `T` ergeben einen `ConfigError` mit beiden Namen.
- `SystemPrompt(PluginInstructions(), Observe.refs)` rendert `refs` zuletzt und genau einmal.
- Eine Unterklasse von `Observe`, die `trust` überschreibt, ersetzt das Kit-`Observe`. Die Referenz `Observe.trust`
  platziert dann den überschriebenen Text.

### P2 – `SystemPrompt` überspringt `None`

```python
SystemPrompt(role_text_or_none, PluginInstructions())  # None-Teile fallen weg
```

- Nur `None` wird übersprungen. Andere falsche Typen bleiben `TypeError`, und leere Strings bleiben, wie sie sind.
- Das passt zu `browser_plugins(*plugins)` und ist dieselbe Konvention, die harnessed auch für
  `Agent(plugins=...)` übernehmen sollte (P7).

Abnahme: `SystemPrompt(None, "A", None).render()` ergibt dasselbe wie `SystemPrompt("A").render()`, und
`agent.prompt` zeigt keinen Eintrag für `None`.

### P3 – Kit-eigenes Prompt-Layout

```python
Kit(name, plugins, prompt=SystemPrompt(PromptText(), ..., format=PromptFormat.MARKDOWN))

kit.system_prompt("Custom role.")      # Layout mit eingesetztem Rollentext
kit.system_prompt(None)                # Layout ohne Rollentext (PromptText fällt weg, vgl. P2)
kit.system_prompt(SystemPrompt(...))   # unverändert durchgereicht: der Aufrufer übernimmt das Layout
```

- `PromptText()` ist ein Platzhalter. Er darf höchstens einmal vorkommen. Ein Layout ohne Platzhalter stellt den
  Text an den Anfang.
- Das Layout ist relativ zum Kit: `kit.without(...)` und Ersetzungen gelten auch dort. Referenzen auf Plugins, die das
  Kit nach `without` nicht mehr hat, fallen still weg, so wie heute bei Fragmenten. Dafür ist kein `optional=True`
  nötig. Referenzen auf Typen, die das Kit nie hatte (`Done`), brauchen weiterhin `optional=True`.
- Das Format gehört zum Layout. Ein eigenes `format=` auf `Kit` oder `Agent` ist dann überflüssig.
- Bewusst **keine** Automatik in `Agent`, die das Layout eines Kits stillschweigend nimmt, wenn `system_prompt` ein
  String ist. Bei mehreren Kits wäre unklar, welches Layout gilt. `kit.system_prompt(...)` bleibt explizit und kostet
  eine Zeile.

Abnahme:

- `kit.system_prompt("Role.")` beginnt mit `Role.` und hat danach die Abschnitte in Layout-Reihenfolge.
- `kit.without(FileTools).system_prompt(None)` enthält keinen Abschnitt `FileTools.usage` und wirft keinen Fehler.
- Ein Kit, das ein anderes Kit mit Layout verschachtelt, kann dessen Layout als Gruppe einbetten, etwa mit
  `inner.layout` als `SystemPrompt`-Teil. Das verschachtelte Layout erbt dann das äußere Format, wie heute bei
  verschachtelten `SystemPrompt`s.
- `Kit(prompt=...)` mit einer Referenz auf einen Typ, den das Kit nicht enthält und der nicht `optional` ist, ergibt
  bei der Konstruktion einen `ConfigError`.

### P4 – Fragmente pro Abschnitt statt pro Plugin

Mit P1 (Klassen-Referenzen) und P3 (Kit-Layout) braucht browserrig keine Fragmente mehr. Für Kits, die Fragmente
weiter für Dritte anbieten wollen, sollten Fragmente aber dieselben Teile annehmen wie `SystemPrompt`:

```python
fragments={"observation": (Observe.page_state, Observe.refs, ImageContext.usage)}
```

Heute geht nur ein ganzes Plugin pro Eintrag. Ein Abschnitt wie `Observe.trust` lässt sich deshalb nicht mit einem
anderen Fragment gruppieren, ohne `Observe` dort komplett zu platzieren.

Abnahme: Ein Fragment aus Abschnitts-Referenzen folgt Ersetzungen und `without` wie ein Fragment aus Instanzen.

### P5 – Fragmente nach Typ deklarieren

```python
fragments={"observation": (Observe, ImageContext)}
```

Wird innerhalb des Kits nach `isinstance` aufgelöst. Mehrdeutigkeit innerhalb eines Kits ist ein Fehler bei der
Konstruktion. Damit entfallen die lokalen Variablen nur für die Fragment-Deklaration. P5 ist überflüssig, wenn P3 und
P4 kommen, und eine billige Alternative, falls nicht.

### P6 – Fragmentname `instructions` reservieren

`kit.instructions` ist `kit.fragment("instructions")`. Ein deklariertes Fragment mit diesem Namen überschreibt still
die Vorgabe "alle Plugins in Kit-Reihenfolge". Vorschlag: `Kit(fragments={"instructions": ...})` wirft
`ConfigError("'instructions' is reserved for all kit instructions")`.

### P7 – `Agent(plugins=...)` überspringt `None`

Gleiche Konvention wie P2. Optionale Plugins lassen sich dann inline schreiben
(`plugins=[Secrets(...) if secrets else None]`), und die Filterzeile in der Facade entfällt.

## Kompatibilität

- P1, P2, P3, P5 und P7 sind rein additiv: Was heute einen Fehler ergibt, bekommt eine Bedeutung.
- P1 ändert die Zuordnung von Klassen-Referenzen auf statische `Instructions` von "Identität der Deklaration" zu
  "Typ plus Attributname". Bisher funktionierende Platzierungen bleiben gleich. Neu trifft die Referenz auch
  Unterklassen, die den Abschnitt überschreiben. Heute wären das unplatzierte Abschnitte mit Fehler, also bricht nichts
  still.
- P6 bricht Kits, die ein Fragment `instructions` deklarieren. Ein `DeprecationWarning` in 0.10 und ein Fehler in 0.11
  sind möglich, wenn nötig.

## Offene Fragen

1. Platzierung nach Slot (`PluginInstructions(slot="completion")`) zusätzlich zum Typ? Slots sind stabiler als
   Klassen, wenn Plugins anderer Pakete denselben Slot füllen. Sie sind aber ein zweiter Weg für dasselbe. Vorschlag:
   erst nur Typ, Slot später, wenn ein Fall auftaucht.
2. Sollen mehrere Treffer bei `PluginInstructions(T)` ein Fehler sein oder in Reihenfolge platziert werden? (Vorschlag
   oben: Fehler.)
3. Name des Platzhalters: `PromptText()`, `RoleText()` oder `CallerText()`.

## Umsetzung in browserrig nach dem Release

- `browser_instructions` und die Fragmente aus `browser_kit` entfernen, Layout als `Kit(prompt=...)` deklarieren.
- `Agent.__init__` auf `kit.system_prompt(system_prompt)` umstellen.
- `trust` an die Stelle setzen, die die Prompt-Review vorschlägt: nach Dateien und den übrigen Plugins, direkt vor
  `done` (siehe `review-prompts.md`, Abschnitt 2).
- Tests in `tests/test_kit.py`: Den Test "completion last" um ein `Done` erweitern, das über ein Kit kommt. Den Test
  zu Removals und Replacements auf `kit.system_prompt` umstellen.
- `docs/agent-guide.md`: Das Beispiel mit `browser_instructions(...)` durch `browser_kit().system_prompt(...)`
  ersetzen.
