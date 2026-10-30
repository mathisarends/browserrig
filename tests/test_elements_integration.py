import pytest

from browserrig import ChromeBrowser, DomMode, LaunchBrowser, wait_for_page
from browserrig.core.errors import BrowserError
from browserrig.kinds import ElementOperation
from browserrig.observation import capture
from browserrig.scripts import ELEMENT
from browserrig.scripts.models import ElementArgs
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_select_notifies_bubbling_listeners_and_rejects_disabled_options(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        frame = await tab.main_frame()
        await evaluate(
            frame,
            "document.querySelector('select').innerHTML = "
            "'<option value=one>First</option><option value=two>Second</option>"
            "<option disabled>Unavailable</option>'",
        )
        await evaluate(
            frame,
            "document.body.dataset.events = '';"
            "for (const name of ['input', 'change']) {"
            "  document.body.addEventListener(name, event => {"
            "    document.body.dataset.events += event.type + ',';"
            "  });"
            "}",
        )
        snapshot = await capture(tab, DomMode(), report)
        select = next(element for element in snapshot.elements if element.tag == "select")
        result = await frame.run_on_node(
            select.backend_id,
            ELEMENT,
            ElementArgs(
                operation=ElementOperation.SELECT,
                value="Second",
            ),
            user_gesture=True,
        )
        assert result == {"value": "two"}
        assert await evaluate(frame, "document.body.dataset.events") == "input,change,"
        for value in ("Unavailable", "Missing"):
            with pytest.raises(BrowserError, match="OPTION_NOT_FOUND"):
                await frame.run_on_node(
                    select.backend_id,
                    ELEMENT,
                    ElementArgs(
                        operation=ElementOperation.SELECT,
                        value=value,
                    ),
                    user_gesture=True,
                )


@pytest.mark.parametrize(
    "markup", ["<textarea>Hello</textarea>", "<div contenteditable=true>Hello</div>"]
)
async def test_focus_selects_text_in_native_and_contenteditable_controls(site, markup):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        frame = await tab.main_frame()
        # Both tags are fixed test cases, with no page-controlled JavaScript.
        await evaluate(frame, f"document.body.innerHTML = '{markup}'")
        snapshot = await capture(tab, DomMode(), report)
        element = snapshot.elements[0]
        assert await frame.run_on_node(
            element.backend_id,
            ELEMENT,
            ElementArgs(operation=ElementOperation.FOCUS, value=True),
            user_gesture=True,
        )
        assert await evaluate(frame, "document.activeElement === document.body.firstElementChild")
        selected = await evaluate(
            frame,
            "document.activeElement.localName === 'textarea'"
            " ? document.activeElement.value.slice("
            "     document.activeElement.selectionStart, document.activeElement.selectionEnd)"
            " : getSelection().toString()",
        )
        assert selected == "Hello"


async def test_native_value_setter_preserves_password_redaction_and_value_validation(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        report = await wait_for_page(tab)
        snapshot = await capture(tab, DomMode(), report)
        frame = await tab.main_frame()
        secret = next(element for element in snapshot.elements if element.input_type == "password")
        assert secret.value is None
        assert await frame.run_on_node(
            secret.backend_id,
            ELEMENT,
            ElementArgs(
                operation=ElementOperation.SET_VALUE,
                value="new-secret",
            ),
            user_gesture=True,
        ) == {"value": None}
        assert await evaluate(frame, "document.querySelector('#secret').value") == "new-secret"
        date = next(element for element in snapshot.elements if element.input_type == "date")
        with pytest.raises(BrowserError, match="INVALID_VALUE"):
            await frame.run_on_node(
                date.backend_id,
                ELEMENT,
                ElementArgs(
                    operation=ElementOperation.SET_VALUE,
                    value="invalid-date",
                ),
                user_gesture=True,
            )
        assert any(element.name == "Shadow button" for element in snapshot.elements)
