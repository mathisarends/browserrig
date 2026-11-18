import pytest

from browserrig import (
    Actions,
    BrowserPerception,
    Chrome,
    DomActionChains,
    DomCapture,
    DomRenderer,
    PageReadiness,
    ReadinessOptions,
    Screenshots,
    TrimInBatches,
)
from browserrig.browser import Launch


@pytest.mark.parametrize(
    ("build", "attribute", "base"),
    [
        pytest.param(Chrome, "options", Launch, id="browser-options"),
        pytest.param(
            PageReadiness, "options", ReadinessOptions, id="readiness-options"
        ),
        pytest.param(
            lambda value: Screenshots(retention=value),
            "retention",
            TrimInBatches,
            id="image-retention",
        ),
        pytest.param(
            lambda value: BrowserPerception(capture=value, renderer=DomRenderer()),
            "capture_strategy",
            DomCapture,
            id="capture-strategy",
        ),
        pytest.param(
            lambda value: BrowserPerception(screenshots=value),
            "screenshots",
            Screenshots,
            id="screenshots",
        ),
        pytest.param(
            lambda value: Actions(chain_policy=value),
            "chain_policy",
            DomActionChains,
            id="action-chain-policy",
        ),
    ],
)
def test_explicit_falsy_configuration_is_preserved(build, attribute, base):
    value = type("FalsyConfiguration", (base,), {"__bool__": lambda self: False})()
    assert not value
    assert getattr(build(value), attribute) is value
