class BrowserError(Exception):
    """An actionable browser failure, without endpoint credentials."""


class BrowserClosed(BrowserError):
    pass


class StaleElement(BrowserError):
    pass


class ReadinessError(BrowserError):
    pass


class SecretError(BrowserError):
    """A secret could not be used; messages name secrets, never their values."""
