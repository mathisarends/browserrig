__version__ = "0.1.0"

from browserrig.core.geometry import Point

from .activity import Activity
from .agent import BrowserAgent
from .browser import Browser, Chrome, ChromeBrowser, ConnectBrowser, LaunchBrowser, Viewport
from .composition import browser_plugins
from .files import FileSystem, FileSystemOptions
from .kinds import DragMode, MouseEventKind
from .nudges import Nudges
from .observation import CanvasMode, DomMode, Observe
from .readiness import Readiness, ReadinessOptions, wait_for_page
from .recording import Recording, RecordingOptions
from .terminal import TerminalEvents
from .tools import Actions

__all__ = [
    "Activity",
    "Actions",
    "Point",
    "DragMode",
    "MouseEventKind",
    "Browser",
    "BrowserAgent",
    "CanvasMode",
    "Chrome",
    "ChromeBrowser",
    "ConnectBrowser",
    "DomMode",
    "FileSystem",
    "FileSystemOptions",
    "LaunchBrowser",
    "Nudges",
    "Observe",
    "Readiness",
    "ReadinessOptions",
    "Recording",
    "RecordingOptions",
    "Viewport",
    "TerminalEvents",
    "browser_plugins",
    "wait_for_page",
]
