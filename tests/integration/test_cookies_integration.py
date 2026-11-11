"""Consent recognition uses the same real snapshots and refs as other page controls."""

import json

import pytest

from browserrig import ChromeBrowser, DomCapture, Input, wait_for_page
from browserrig.browser import Launch
from browserrig.core import Point
from browserrig.observation import capture, render
from tests.javascript import evaluate

pytestmark = pytest.mark.integration

_CHOICES = "<button>Accept all</button><button>Reject all</button>"
_NOTICE = "<p>We use cookies to personalize content.</p>" + _CHOICES


@pytest.mark.parametrize(
    "markup",
    [
        f"<div style='position:fixed;bottom:0'>{_NOTICE}</div>",
        "<div id=cookie-banner><p>Diese Seite verwendet Cookies.</p>"
        "<button>Verstanden</button></div>",
        "<div role=dialog aria-modal=true aria-label='Cookie preferences'>"
        "<p>Cookies help us improve this site.</p><button>Only necessary</button></div>",
        "<dialog open><h2>Cookie settings</h2><p>We use cookies.</p>"
        "<button>Save preferences</button></dialog>",
        f"<section>{_NOTICE}</section>",
        "<div id=onetrust-banner-sdk><p>Your privacy and consent choices</p>"
        f"{_CHOICES}</div>",
        "<aside style='position:sticky;top:0'><p>Wir verwenden Cookies.</p>"
        "<button>Alle akzeptieren</button><button>Alle ablehnen</button></aside>",
        "<div style='position:absolute'><p>Nous utilisons des cookies.</p>"
        "<button>Accepter</button><button>Refuser</button></div>",
        f"<div id=cookie-consent><div class=cookie-banner><div>{_NOTICE}</div></div></div>",
        "<div style='position:fixed'><p>We use cookies for analytics.</p>"
        "<div><button>Accept cookies</button><button>Reject cookies</button></div></div>",
        "<div class=didomi-popup><p>We value your privacy.</p><button>Accept all</button></div>",
        "<div id=cookie-banner><p>We use cookies.</p><div onclick=''>Accept all</div></div>",
        "<div id=cookie-banner><p>We use cookies.</p><button disabled>Accept all</button></div>",
    ],
    ids=[
        "fixed",
        "notice",
        "aria-dialog",
        "native-dialog",
        "unstyled",
        "vendor",
        "german",
        "french",
        "nested",
        "nested-buttons",
        "privacy-without-rejection",
        "custom-button",
        "disabled-button",
    ],
)
async def test_cookie_banner_has_context_and_existing_action_refs(site, markup):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(
            tab, DomCapture(max_text_chars=0, sparse_text_chars=0), report
        )
        assert not state.text
        assert len(state.cookie_banners) == 1
        banner = state.cookie_banners[0]
        assert banner.text and banner.refs
        if "analytics" in markup:
            assert "analytics" in banner.text
        assert all(state.element(ref).in_viewport for ref in banner.refs)
        text = render(state)
        assert "cookie banners: 1 detected heuristically" in text
        assert "[COOKIE BANNER:" in text and banner.text in text
        for ref in banner.refs:
            assert text.count(f"[{ref}]") == 1
        if state.modal:
            assert banner.modal and "interact with it first" not in text


@pytest.mark.parametrize(
    "markup",
    [
        "<footer><button>Cookie settings</button><a href='/privacy'>Cookie policy</a></footer>",
        "<article><h1>How cookies work</h1><p>We explain cookies.</p>"
        "<button>Accept terms</button><button>Reject terms</button></article>",
        "<div style='position:fixed'><p>Privacy matters. Join our newsletter.</p>"
        "<button>Accept invitation</button></div>",
        f"<div hidden id=cookie-banner>{_NOTICE}</div>",
        f"<div style='display:none' id=cookie-banner>{_NOTICE}</div>",
        f"<div style='opacity:0' id=cookie-banner>{_NOTICE}</div>",
        f"<div style='position:absolute;top:3000px' id=cookie-banner>{_NOTICE}</div>",
        f"<div style='position:fixed;inset:0;background:white'>{_NOTICE}</div>"
        "<div style='position:fixed;inset:0;background:white;z-index:100'>Other overlay</div>",
        "<div style='position:fixed'><p style='position:absolute;top:3000px'>We use cookies.</p>"
        "<p>Newsletter subscription</p><button>Accept invitation</button></div>",
    ],
    ids=[
        "footer",
        "article",
        "newsletter",
        "hidden",
        "display-none",
        "transparent",
        "offscreen",
        "covered",
        "offscreen-text",
    ],
)
async def test_content_and_invisible_banners_are_not_reported(site, markup):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        assert not state.cookie_banners
        assert "COOKIE BANNER" not in render(state)


async def test_banner_text_survives_busy_page_and_disappears_after_normal_click(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        devices = Input(browser.input_targets.focused)
        tab = browser.active_tab
        await wait_for_page(tab)
        markup = "<nav>" + "<button>Navigation</button>" * 6 + "</nav>"
        markup += (
            "<div id=cookie-banner style='position:fixed;bottom:0'>"
            "<h2>Privacy choices</h2><p>We use cookies for analytics.</p>"
            "<button onclick='this.parentElement.remove()'>Reject all</button></div>"
        )
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        before = await capture(
            tab, DomCapture(max_text_chars=0, sparse_text_chars=0), report
        )
        assert not before.text and len(before.cookie_banners) == 1
        banner = before.cookie_banners[0]
        assert banner.name == "Privacy choices" and "analytics" in banner.text
        button = before.element(banner.refs[0])
        assert button.name == "Reject all" and button.bounds is not None
        bounds = button.bounds
        await devices.mouse.click(
            Point(x=bounds.x + bounds.width / 2, y=bounds.y + bounds.height / 2)
        )
        report = await wait_for_page(tab)
        after = await capture(tab, DomCapture(), report, previous=before)
        assert not after.cookie_banners and after.fingerprint != before.fingerprint
        assert "COOKIE BANNER" not in render(after)


@pytest.mark.parametrize("surface", ["closed-shadow", "frame", "cross-origin-frame"])
async def test_consent_inside_composed_documents(site, surface):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        if surface == "closed-shadow":
            await evaluate(tab, "document.body.innerHTML = '<div id=host></div>'")
            await evaluate(
                tab,
                "document.querySelector('#host').attachShadow({mode:'closed'}).innerHTML = "
                + json.dumps(f"<div style='position:fixed;bottom:0'>{_NOTICE}</div>"),
            )
        else:
            await evaluate(tab, "document.body.innerHTML = '<iframe></iframe>'")
            # srcdoc with an opaque sandbox origin also exercises an isolated document.
            await evaluate(
                tab,
                "const frame=document.querySelector('iframe');"
                + (
                    "frame.setAttribute('sandbox','allow-scripts');"
                    if surface == "cross-origin-frame"
                    else ""
                )
                + "frame.srcdoc = "
                + json.dumps(_NOTICE),
            )
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        assert len(state.cookie_banners) == 1
        assert {state.element(ref).name for ref in state.cookie_banners[0].refs} == {
            "Accept all",
            "Reject all",
        }


async def test_banner_remains_actionable_under_element_limit(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        markup = "<nav>" + "<button>Navigation</button>" * 8 + "</nav>"
        markup += f"<div id=cookie-banner>{_NOTICE}</div>"
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(max_elements=1), report)
        assert len(state.elements) == 1 and len(state.cookie_banners) == 1
        assert state.cookie_banners[0].refs == (state.elements[0].ref,)
        assert state.elements[0].name == "Accept all"


async def test_multiple_banners_have_separate_bounded_excerpts(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        markup = (
            "<div id=cookie-banner><p>We use cookies. "
            + "Details. " * 120
            + f"</p>{_CHOICES}</div><aside id=consent-dialog>{_NOTICE}</aside>"
        )
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        report = await wait_for_page(tab)
        state = await capture(tab, DomCapture(), report)
        assert len(state.cookie_banners) == 2
        first, second = state.cookie_banners
        assert len(first.text) == 600 and first.text.endswith("…")
        assert "personalize" in second.text
        assert not set(first.refs).intersection(second.refs)
