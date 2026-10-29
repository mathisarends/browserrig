"""Composable Chrome automation. Importing this package opens no resources."""

__version__ = "0.1.0"

from .activity import Activity
from .browser import Browser, Chrome, ChromeBrowser, ConnectBrowser, LaunchBrowser, Viewport
from .browser.models import Point
from .composition import browser_plugins
from .kinds import DragMode
from .nudges import Nudges
from .observation import FigmaMode, WebMode
from .observation.plugin import Observe
from .readiness import wait_for_page
from .readiness.config import ReadinessOptions
from .readiness.plugin import Readiness
from .recording import Recording, RecordingOptions
from .tools.execution import Actions

__all__ = [
    "Activity",
    "Actions",
    "Point",
    "DragMode",
    "Browser",
    "FigmaMode",
    "Chrome",
    "ChromeBrowser",
    "ConnectBrowser",
    "WebMode",
    "LaunchBrowser",
    "Nudges",
    "Observe",
    "Readiness",
    "ReadinessOptions",
    "Recording",
    "RecordingOptions",
    "Viewport",
    "browser_plugins",
    "wait_for_page",
]
