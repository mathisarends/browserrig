import pytest

from browserrig import ChromeBrowser, DomMode, LaunchBrowser, wait_for_page
from browserrig.core.errors import BrowserError
from browserrig.kinds import ElementOperation
from browserrig.observation.capture import ELEMENT_SCRIPT, capture

pytestmark = pytest.mark.integration


async def test_select_notifies_bubbling_listeners_and_rejects_disabled_options(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        frame = await tab.main_frame()
        await frame.evaluate(
            "document.querySelector('select').innerHTML = "
            "'<option value=one>First</option><option value=two>Second</option>"
            "<option disabled>Unavailable</option>'"
        )
        await frame.evaluate(
            "document.body.dataset.events = '';"
            "for (const name of ['input', 'change']) {"
            "  document.body.addEventListener(name, event => {"
            "    document.body.dataset.events += event.type + ',';"
            "  });"
            "}"
        )
        snapshot = await capture(browser, tab, DomMode(), report)
        select = next(element for element in snapshot.elements if element.tag == "select")
        result = await frame.call(
            ELEMENT_SCRIPT, snapshot.id, select.index, ElementOperation.SELECT, "Second"
        )
        assert result == {"value": "two"}
        assert await frame.evaluate("document.body.dataset.events") == "input,change,"
        for value in ("Unavailable", "Missing"):
            with pytest.raises(BrowserError, match="OPTION_NOT_FOUND"):
                await frame.call(
                    ELEMENT_SCRIPT, snapshot.id, select.index, ElementOperation.SELECT, value
                )


@pytest.mark.parametrize(
    "markup", ["<textarea>Hello</textarea>", "<div contenteditable=true>Hello</div>"]
)
async def test_focus_selects_text_in_native_and_contenteditable_controls(site, markup):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        frame = await tab.main_frame()
        # Both tags are fixed test cases, with no page-controlled JavaScript.
        await frame.evaluate(f"document.body.innerHTML = '{markup}'")
        snapshot = await capture(browser, tab, DomMode(), report)
        element = snapshot.elements[0]
        assert await frame.call(
            ELEMENT_SCRIPT, snapshot.id, element.index, ElementOperation.FOCUS, True
        )
        assert await frame.evaluate("document.activeElement === document.body.firstElementChild")
        selected = await frame.evaluate(
            "document.activeElement.localName === 'textarea'"
            " ? document.activeElement.value.slice("
            "     document.activeElement.selectionStart, document.activeElement.selectionEnd)"
            " : getSelection().toString()"
        )
        assert selected == "Hello"


async def test_native_value_setter_preserves_password_redaction_and_value_validation(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(browser, tab)
        snapshot = await capture(browser, tab, DomMode(), report)
        frame = await tab.main_frame()
        secret = next(element for element in snapshot.elements if element.input_type == "password")
        assert secret.value is None
        assert await frame.call(
            ELEMENT_SCRIPT, snapshot.id, secret.index, ElementOperation.SET_VALUE, "new-secret"
        ) == {"value": None}
        assert await frame.evaluate("document.querySelector('#secret').value") == "new-secret"
        date = next(element for element in snapshot.elements if element.input_type == "date")
        with pytest.raises(BrowserError, match="INVALID_VALUE"):
            await frame.call(
                ELEMENT_SCRIPT, snapshot.id, date.index, ElementOperation.SET_VALUE, "invalid-date"
            )
        assert any(element.name == "Shadow button" for element in snapshot.elements)
