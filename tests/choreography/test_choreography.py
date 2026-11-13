"""What viewers see and how long the harness pauses, for staged browser actions.

Each timeline interleaves emitted events, pauses and browser calls in the order they
happen, so moving the staging between modules cannot change it unnoticed.
"""

import asyncio
import inspect
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from browserrig.choreography import (
    BarTypedEvent,
    CursorEnteredEvent,
    FileTransferEvent,
    FindBarEvent,
    FindResultsEvent,
    HighlightElementEvent,
    InputVisualization,
    TabPressedEvent,
    WaitingEvent,
    scenes,
)
from browserrig.core import Bounds, ElementPoint, Point, TabGesture
from browserrig.events import (
    ActionFinishedEvent,
    ActionStartedEvent,
    CursorMovedEvent,
    CursorStateEvent,
    FileOpenedEvent,
    FilesUploadedEvent,
    InputEvent,
    KeyboardVisibilityEvent,
    KeyPressedEvent,
    NavigationStartedEvent,
)
from browserrig.files import FileSystem, LocalWorkspace, MountedWorkspace
from browserrig.input import mouse as mouse_module
from browserrig.observation.content import PageContent
from browserrig.pacing import InputPacing
from browserrig.scripts import FindResult
from browserrig.tools import Actions, FileTools, NavigationTools, PageSearchTools
from browserrig.tools import search as search_module
from browserrig.tools import targeting as targeting_module
from tests.fakes import mounted

# The plugins that pace input like a person and stage actions for viewers.
STAGING = (InputPacing, InputVisualization)


class _Frame:
    id = "frame"
    parent = None
    local_visible = None
    visible = None

    def __init__(self, timeline):
        self._timeline = timeline

    async def run(self, _script, args):
        if args.close:
            self._timeline.append("find closed")
            return None
        self._timeline.append(
            f"find {'|'.join(args.queries)} reveal={args.reveal} ticks={args.ticks}"
        )
        return FindResult(total=3, counts=(3,) * len(args.queries), ticks=(0.1, 0.9))


class _Tab:
    """A tab that records its input, navigation and find calls on the timeline."""

    def __init__(self, timeline, tab_id):
        self.input = self
        self.id = tab_id
        self.document_id = f"{tab_id}-document"
        self.url = "https://example.org/"
        self.title = "Example"
        self.dialog = None
        self.navigation_pending = False
        self.closed = False
        self.frame_limitations = ()
        self._timeline = timeline
        self._frame = _Frame(timeline)

    async def sync_document(self):
        pass

    async def frames(self):
        return (self._frame,)

    def check_navigation(self):
        pass

    async def emit(self, event):
        self._timeline.append(
            replace(event, target_id=self.id, document_id=self.document_id)
        )

    async def navigate(self, url):
        self._timeline.append(f"navigate {url}")

    async def dispatch_mouse(self, kind, point, **_):
        self._timeline.append(f"mouse {kind} {point.x:g},{point.y:g}")

    async def dispatch_key(self, kind, *, key, **_):
        self._timeline.append(f"key {kind} {key}")

    async def viewport_size(self):
        return 1000, 800

    async def cursor_style(self, _point):
        return None

    def layout_changed(self):
        pass


@pytest.fixture(name="timeline")
def _timeline(monkeypatch):
    timeline = []
    pause = asyncio.sleep
    clock = SimpleNamespace(now=0.0)

    async def sleep(seconds, result=None):
        caller = inspect.currentframe().f_back
        if caller.f_globals.get("__name__", "").startswith("browserrig"):
            timeline.append(f"sleep {seconds:.2f}")
        clock.now += seconds
        await pause(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", sleep)
    # Fake pauses and elapsed-time accounting must use the same clock, so runner
    # scheduling cannot shorten the remaining key interval in timeline assertions.
    monkeypatch.setattr(scenes, "monotonic", lambda: clock.now)
    monkeypatch.setattr(mouse_module, "monotonic", lambda: clock.now)
    return timeline


@asynccontextmanager
async def _staged(timeline, *plugins, staging=STAGING, files=None):
    staged = tuple(plugin() for plugin in staging)
    bridge = MountedWorkspace() if files is not None else None
    async with mounted(*staged, Actions(), *plugins, bridge=bridge, files=files) as (
        services,
        ctx,
    ):
        services.events = timeline
        browser = services.browser
        browser.active_tab = _Tab(timeline, "tab-1")
        opened = iter(range(2, 10))

        async def open_tab(_target="about:blank"):
            tab = _Tab(timeline, f"tab-{next(opened)}")

            async def show() -> None:
                browser.active_tab = tab

            await services.input.mouse.switch_tab(TabGesture.OPEN, "", show)
            return tab

        browser.tabs.open = open_tab
        yield services, ctx


def _shown(timeline) -> list[str]:
    """The timeline as text; input inside an action must be attributed to it."""
    shown = []
    action = ""
    for entry in timeline:
        if isinstance(entry, ActionStartedEvent):
            action = entry.action_id
        if isinstance(entry, InputEvent) and entry.action_id != action:
            raise AssertionError(f"{entry} is not attributed to action {action!r}")
        if isinstance(entry, ActionFinishedEvent):
            action = ""
        shown.append(entry if isinstance(entry, str) else _describe(entry))
    return shown


def _describe(event) -> str:  # pylint: disable=too-many-return-statements,too-many-branches
    match event:
        case ActionStartedEvent(kind=kind):
            return f"{kind} started"
        case ActionFinishedEvent(kind=kind):
            return f"{kind} finished"
        case KeyPressedEvent(key=key, modifiers=modifiers, duration=duration):
            return f"shows key {'+'.join((*modifiers, key))} {duration:.2f}"
        case KeyboardVisibilityEvent(visible=visible):
            return "keyboard shown" if visible else "keyboard hidden"
        case BarTypedEvent(browser_bar=where, key=key, text=text, duration=duration):
            return f"{where} bar {key} -> {text!r} {duration:.2f}"
        case FindBarEvent(visible=visible):
            return "find bar open" if visible else "find bar closed"
        case FindResultsEvent(query=query, label=label, ticks=ticks):
            return f"results {query!r} {label} ticks={list(ticks)}"
        case WaitingEvent(duration=duration):
            return f"waiting {duration:g}"
        case FileTransferEvent(direction=direction, x=x, y=y, duration=duration):
            return f"transfer {direction} at {x},{y} {duration:.2f}"
        case HighlightElementEvent(ref=ref):
            return f"highlight {ref}"
        case TabPressedEvent(gesture=gesture, tab_id=tab_id, duration=duration):
            return f"tab {gesture} {tab_id!r} from {event.target_id} {duration:.2f}"
        case CursorEnteredEvent(to_position=(x, y), duration=duration):
            return f"cursor enters {event.target_id} at {x:g},{y:g} {duration:.2f}"
        case CursorMovedEvent(to_position=(x, y), duration=duration):
            return f"cursor moves to {x:g},{y:g} {duration:.2f}"
        case CursorStateEvent(x=x, y=y):
            return f"cursor rests in {event.target_id} at {x:g},{y:g}"
        case NavigationStartedEvent(url=url, typed=typed):
            return f"navigation to {url} started as {typed!r}"
        case FileOpenedEvent(target_id=target_id):
            return f"file opened in {target_id}"
        case FilesUploadedEvent(paths=paths):
            return f"uploaded {len(paths)} file"
    raise AssertionError(f"No description for {event}")


class _SearchTools(PageSearchTools, provides=True):
    """Expose the mounted plugin, so tests can call its tool directly."""


class _NavigationTools(NavigationTools, provides=True):
    pass


class _FileTools(FileTools, provides=True):
    pass


async def test_search_page_types_into_the_find_bar_and_shows_records_without_scrolling(
    timeline, monkeypatch
):
    _page(monkeypatch, timeline)
    async with _staged(timeline, _SearchTools()) as (_, ctx):
        result = await ctx[_SearchTools].search_page("ab", ("c",))
    assert result.text.startswith('1 record matches "ab" | "c"')
    assert _shown(timeline) == [
        "shows key Control+f 0.00",
        "find bar open",
        "keyboard shown",
        "find bar a -> 'a' 0.05",
        "find a reveal=False ticks=True",
        "results 'a' 3 matches ticks=[0.1, 0.9]",
        "sleep 0.05",
        "find bar b -> 'ab' 0.05",
        "find ab reveal=False ticks=True",
        "results 'ab' 3 matches ticks=[0.1, 0.9]",
        "sleep 0.05",
        "find bar   -> 'ab ' 0.05",
        "find ab reveal=False ticks=True",
        "results 'ab ' 3 matches ticks=[0.1, 0.9]",
        "sleep 0.05",
        "find bar | -> 'ab |' 0.05",
        "find ab reveal=False ticks=True",
        "results 'ab |' 3 matches ticks=[0.1, 0.9]",
        "sleep 0.05",
        "find bar   -> 'ab | ' 0.05",
        "find ab reveal=False ticks=True",
        "results 'ab | ' 3 matches ticks=[0.1, 0.9]",
        "sleep 0.05",
        "find bar c -> 'ab | c' 0.05",
        "find ab|c reveal=False ticks=True",
        "results 'ab | c' 3 matches ticks=[0.1, 0.9]",
        "sleep 0.05",
        "keyboard hidden",
        "page read",
        "find ab|c reveal=False ticks=True",
        "results 'ab | c' 1 record ticks=[0.1, 0.9]",
        "sleep 0.60",
        "shows key Escape 0.00",
        "find bar closed",
        "find closed",
    ]


def _page(monkeypatch, timeline):
    async def extract(_tab, *, full_page):  # pylint: disable=unused-argument
        timeline.append("page read")
        return PageContent(url="https://example.org/", title="Example", markdown="ab")

    monkeypatch.setattr(search_module, "extract_document", extract)


async def test_navigate_types_the_address_before_the_page_loads(timeline):
    async with _staged(timeline, _NavigationTools()) as (_, ctx):
        await ctx[_NavigationTools].navigate("https://ab.cd/")
    assert _shown(timeline) == [
        "navigate started",
        "keyboard shown",
        "address bar a -> 'a' 0.05",
        "sleep 0.05",
        "address bar b -> 'ab' 0.05",
        "sleep 0.05",
        "address bar . -> 'ab.' 0.05",
        "sleep 0.05",
        "address bar c -> 'ab.c' 0.05",
        "sleep 0.05",
        "address bar d -> 'ab.cd' 0.05",
        "sleep 0.05",
        "address bar Enter -> 'ab.cd' 0.05",
        "sleep 0.05",
        "keyboard hidden",
        "navigation to https://ab.cd/ started as 'ab.cd'",
        "navigate https://ab.cd/",
        "navigate finished",
    ]


async def test_navigate_in_a_new_tab_opens_it_before_typing_there(timeline):
    async with _staged(timeline, _NavigationTools()) as (_, ctx):
        await ctx[_NavigationTools].navigate("https://a.b/", new_tab=True)
    assert _shown(timeline) == [
        "navigate started",
        "tab open '' from tab-1 0.45",
        "sleep 0.45",
        "cursor enters tab-2 at 500,400 0.35",
        "sleep 0.35",
        "mouse mouseMoved 500,400",
        "cursor rests in tab-2 at 500,400",
        "keyboard shown",
        "address bar a -> 'a' 0.05",
        "sleep 0.05",
        "address bar . -> 'a.' 0.05",
        "sleep 0.05",
        "address bar b -> 'a.b' 0.05",
        "sleep 0.05",
        "address bar Enter -> 'a.b' 0.05",
        "sleep 0.05",
        "keyboard hidden",
        "navigation to https://a.b/ started as 'a.b'",
        "navigate https://a.b/",
        "navigate finished",
    ]


async def test_wait_announces_its_duration_then_pauses(timeline):
    async with _staged(timeline, _NavigationTools()) as (_, ctx):
        await ctx[_NavigationTools].wait(2)
    assert _shown(timeline) == ["waiting 2", "sleep 2.00"]


async def test_open_file_moves_the_file_out_before_the_new_tab_opens(
    timeline, tmp_path
):
    files = FileSystem(LocalWorkspace(tmp_path))
    await files.write_file("report.txt", "report")
    async with _staged(timeline, _FileTools(), files=files) as (_, ctx):
        await ctx[_FileTools].open_file("report.txt")
    assert _shown(timeline) == [
        "open_file started",
        "transfer open at None,None 0.45",
        "sleep 0.45",
        "tab open '' from tab-1 0.45",
        "sleep 0.45",
        "cursor enters tab-2 at 500,400 0.35",
        "sleep 0.35",
        "mouse mouseMoved 500,400",
        "cursor rests in tab-2 at 500,400",
        "file opened in tab-2",
        "open_file finished",
    ]


async def test_upload_highlights_the_input_and_drops_the_files_onto_it(
    timeline, tmp_path, monkeypatch
):
    files = FileSystem(LocalWorkspace(tmp_path))
    await files.write_file("report.txt", "report")

    async def upload(paths):
        timeline.append(f"upload {len(paths)} file")

    async def locate(*, aim):
        assert aim == (0.5, 0.5)
        return ElementPoint(x=40, y=30, bounds=Bounds(x=0, y=0, width=80, height=60))

    handle = SimpleNamespace(
        element=SimpleNamespace(
            input_type="file",
            bounds=None,
            in_viewport=True,
            covered=False,
            upload_label_ref=None,
        ),
        upload_files=upload,
        locate=locate,
    )

    async def element(_tab, _ref):
        return handle

    async def prepare(*_, **_kwargs):
        return False

    monkeypatch.setattr(targeting_module, "prepare_element", prepare)
    async with _staged(timeline, _FileTools(), files=files) as (services, ctx):
        services.observe.element = element
        # Already resting on the input, so the pointer does not travel.
        await services.input.mouse.move_to(Point(x=40, y=30))
        timeline.clear()
        await ctx[_FileTools].upload_files("input", ["report.txt"])
    assert _shown(timeline) == [
        "upload started",
        "highlight input",
        "cursor moves to 40,30 0.00",
        "mouse mouseMoved 40,30",
        "cursor rests in tab-1 at 40,30",
        "highlight input",
        "transfer upload at 40.0,30.0 0.45",
        "sleep 0.45",
        "upload 1 file",
        "uploaded 1 file",
        "upload finished",
    ]


async def test_switching_back_returns_to_where_the_pointer_rested(timeline):
    async with _staged(timeline) as (services, _):
        browser = services.browser
        first = browser.active_tab
        await services.input.mouse.move_to(Point(x=10, y=0))
        await browser.tabs.open()
        timeline.clear()

        async def back() -> None:
            browser.active_tab = first

        await services.input.mouse.switch_tab(TabGesture.ACTIVATE, first.id, back)
    assert _shown(timeline) == [
        "tab activate 'tab-1' from tab-2 0.45",
        "sleep 0.45",
        "cursor enters tab-1 at 10,0 0.35",
        "sleep 0.35",
        "mouse mouseMoved 10,0",
        "cursor rests in tab-1 at 10,0",
    ]


async def test_typing_paces_each_key(timeline):
    async with _staged(timeline) as (services, _):
        await services.input.keyboard.type_text("aB")
    assert _shown(timeline) == [
        "keyboard shown",
        "key rawKeyDown a",
        "key char a",
        "key keyUp a",
        "shows key a 0.05",
        "sleep 0.05",
        "key rawKeyDown Shift",
        "key rawKeyDown B",
        "key char B",
        "key keyUp B",
        "key keyUp Shift",
        "shows key Shift+B 0.05",
        "sleep 0.05",
        "keyboard hidden",
    ]


async def test_pointer_travels_along_an_eased_path(timeline):
    async with _staged(timeline) as (services, _):
        await services.input.mouse.move_to(Point(x=300, y=0))
    moved, *steps, rested = _shown(timeline)
    # 300 px take 0.05 + 0.075 * log2(16) seconds, at 60 steps per second.
    assert moved == "cursor moves to 300,0 0.35"
    assert steps[-2:] == ["mouse mouseMoved 300,0", "sleep 0.02"]
    assert steps.count("sleep 0.02") == 21
    assert rested == "cursor rests in tab-1 at 300,0"


# Without staging, tools and devices do the same work at full speed and show nothing.


async def test_unstaged_search_only_reads_the_page(timeline, monkeypatch):
    _page(monkeypatch, timeline)
    async with _staged(timeline, _SearchTools(), staging=()) as (_, ctx):
        await ctx[_SearchTools].search_page("ab", ("c",))
    assert _shown(timeline) == ["page read"]


async def test_unstaged_navigate_loads_right_away(timeline):
    async with _staged(timeline, _NavigationTools(), staging=()) as (_, ctx):
        await ctx[_NavigationTools].navigate("https://a.b/", new_tab=True)
    assert _shown(timeline) == [
        "navigate started",
        "mouse mouseMoved 500,400",
        "navigation to https://a.b/ started as 'a.b'",
        "navigate https://a.b/",
        "navigate finished",
    ]


async def test_unstaged_wait_only_waits(timeline):
    async with _staged(timeline, _NavigationTools(), staging=()) as (_, ctx):
        await ctx[_NavigationTools].wait(2)
    assert _shown(timeline) == ["sleep 2.00"]


async def test_unstaged_input_types_and_moves_without_pauses(timeline):
    async with _staged(timeline, staging=()) as (services, _):
        await services.input.keyboard.type_text("a")
        await services.input.mouse.move_to(Point(x=300, y=0))
    assert _shown(timeline) == [
        "key rawKeyDown a",
        "key char a",
        "key keyUp a",
        "mouse mouseMoved 300,0",
    ]
