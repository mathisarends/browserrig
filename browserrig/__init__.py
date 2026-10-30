__version__ = "0.1.0"

from browserrig.core.geometry import Point

from .activity import Activity
from .agent import BrowserAgent
from .browser import Browser, Chrome, ChromeBrowser, ConnectBrowser, LaunchBrowser, Viewport
from .composition import browser_plugins
from .files import FileSystem, FileSystemOptions
from .kinds import MouseEventKind
from .nudges import Nudges
from .observation import (
    CanvasCapture,
    CanvasMode,
    CanvasRegion,
    CanvasRenderer,
    CaptureContent,
    CaptureRegion,
    CaptureStrategy,
    DomCapture,
    DomMode,
    DomRenderer,
    ImageContext,
    ImageRetention,
    Observe,
    Renderer,
    Screenshots,
    ScreenshotTrigger,
    TrimInBatches,
    UntilCompaction,
)
from .readiness import (
    CanvasReady,
    DocumentReadiness,
    DomReady,
    Readiness,
    ReadinessContext,
    ReadinessOptions,
    ReadinessPolicy,
    ReadinessStrategy,
    wait_for_page,
)
from .recording import Recording, RecordingOptions
from .secrets import Secret, Secrets, Totp, env, totp
from .terminal import TerminalEvents
from .tools import (
    Actions,
    DomActionChains,
    DomTools,
    KeyboardTools,
    MouseTools,
    NavigationTools,
    ObserveAfterInput,
    PointerTools,
    TabTools,
)

__all__ = [
    "CanvasCapture",
    "CanvasRegion",
    "CanvasRenderer",
    "CaptureContent",
    "CaptureRegion",
    "CaptureStrategy",
    "DomCapture",
    "DomRenderer",
    "ImageContext",
    "ImageRetention",
    "TrimInBatches",
    "UntilCompaction",
    "Renderer",
    "Screenshots",
    "ScreenshotTrigger",
    "CanvasReady",
    "DocumentReadiness",
    "DomReady",
    "ReadinessContext",
    "ReadinessPolicy",
    "ReadinessStrategy",
    "DomTools",
    "PointerTools",
    "KeyboardTools",
    "NavigationTools",
    "TabTools",
    "ObserveAfterInput",
    "DomActionChains",
    "Activity",
    "Actions",
    "Point",
    "MouseEventKind",
    "MouseTools",
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
    "Secret",
    "Secrets",
    "Totp",
    "env",
    "totp",
    "Viewport",
    "TerminalEvents",
    "browser_plugins",
    "wait_for_page",
]
