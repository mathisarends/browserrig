from browserrig.core.tools import BrowserToolMetadata, browser_tool

from .dialogs import DialogTools
from .execution import Actions
from .files import FileTools, UploadTools
from .forms import FormTools
from .javascript import JavaScriptTools
from .keyboard import KeyboardTools
from .mouse import MouseTools
from .navigation import NavigationTools
from .tabs import TabTools

__all__ = [
    "BrowserToolMetadata",
    "browser_tool",
    "Actions",
    "DialogTools",
    "FileTools",
    "FormTools",
    "JavaScriptTools",
    "KeyboardTools",
    "MouseTools",
    "NavigationTools",
    "TabTools",
    "UploadTools",
]
