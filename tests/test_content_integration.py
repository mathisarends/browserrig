import json

import pytest

from browserrig import ChromeBrowser, DomMode, LaunchBrowser, wait_for_page
from browserrig.kinds import ElementOperation
from browserrig.observation import capture
from browserrig.observation.content import extract_content
from browserrig.scripts import ELEMENT
from browserrig.scripts.models import ElementArgs
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_structured_markdown_reads_full_document_and_preserves_element_refs(site):
    markup = """<h1>Mission report</h1><p>A <strong>bold</strong> and <em>small</em> step.
        <a href='/other?q=1&x=2'>Details</a><img alt='Space probe' src='/missing'></p>
        <ul><li>First item<ul><li>Nested item</li></ul></li><li>Second item</li></ul>
        <ol start=3><li>Third</li><li>Fourth</li></ol>
        <table><caption>Results</caption><tr><th>Mission</th><th>Value</th></tr>
        <tr><td>Voyager</td><td>A | B</td></tr></table>
        <blockquote>Quoted text</blockquote>
        <p>Inline <code>a &lt; b</code></p><pre><code>line one\n\n\n  line two\n```</code></pre>
        <div hidden>Hidden attribute</div><div style='display:none'>Hidden display</div>
        <div aria-hidden=true>Hidden aria</div><div style='opacity:0'>Transparent</div>
        <details><summary>Closed summary</summary>Closed details secret</details>
        <details open><summary>Open summary</summary>Open details text</details>
        <input type=password value=never-echo-this><textarea>Private draft</textarea>
        <button>Continue</button><div id=open><span slot=label>Slotted text</span></div>
        <div id=closed></div><script>Script secret</script>
        <div style='position:absolute;top:3000px'>
            <h2>Below viewport</h2><p>Last paragraph</p></div>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await evaluate(
            tab,
            """
            document.querySelector('#open').attachShadow({mode:'open'}).innerHTML =
                '<p>Open shadow <slot name=label></slot></p>';
            document.querySelector('#closed').attachShadow({mode:'closed'}).innerHTML =
                '<h2>Closed shadow</h2><p>Closed root text</p>';
        """,
        )
        report = await wait_for_page(tab)
        snapshot = await capture(tab, DomMode(), report)
        assert snapshot.image is None
        assert snapshot.text == ""
        assert not snapshot.limitations
        before = await evaluate(tab, "[document.documentElement.outerHTML, scrollY]")
        content = await extract_content(tab)
        assert await evaluate(tab, "[document.documentElement.outerHTML, scrollY]") == before
        assert content.url == site + "/" and content.title == "Test form"
        assert not content.limitations
        text = content.markdown
        for expected in (
            "# Mission report",
            "**bold**",
            "*small*",
            f"[Details](<{site}/other?q=1&x=2>)",
            "Space probe",
            "- First item\n\n  - Nested item",
            "- Second item",
            "3. Third\n4. Fourth",
            "| Mission | Value |\n| --- | --- |\n| Voyager | A \\| B |",
            "> Quoted text",
            "` a < b `",
            "````\nline one\n\n\n  line two\n```\n````",
            "Closed summary",
            "Open details text",
            "Open shadow Slotted text",
            "## Closed shadow",
            "Closed root text",
            "## Below viewport",
            "Last paragraph",
        ):
            assert expected in text
        for excluded in (
            "never-echo-this",
            "Private draft",
            "Script secret",
            "Hidden attribute",
            "Hidden display",
            "Hidden aria",
            "Transparent",
            "Closed details secret",
        ):
            assert excluded not in text
        button = next(element for element in snapshot.elements if element.name == "Continue")
        await (await tab.main_frame()).run(
            ELEMENT,
            ElementArgs(
                token=snapshot.id, index=button.index, operation=ElementOperation.POINT, value=False
            ),
            user_gesture=True,
        )


async def test_markdown_limits_are_explicit_and_output_is_bounded(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab, "document.body.innerHTML = '<h1>Heading</h1><p>'+'x'.repeat(500)+'</p>'"
        )
        content = await extract_content(tab, max_chars=40)
        assert len(content.markdown) <= 40
        assert "# Heading" in content.markdown
        assert any("truncated" in item for item in content.limitations)
        assert "Extraction limitations" in content.render()
        assert site in content.render()


@pytest.mark.parametrize("cross_origin", [False, True])
async def test_markdown_includes_available_frame_documents(site, cross_origin):
    async with ChromeBrowser(
        LaunchBrowser(url=site + "/frames", arguments=("--site-per-process",))
    ) as browser:
        tab = browser.active_tab
        origin = site.replace("127.0.0.1", "localhost") if cross_origin else site
        await evaluate(
            tab, f"document.querySelector('iframe').src = {json.dumps(origin + '/other')}"
        )
        await wait_for_page(tab)
        content = await extract_content(tab)
        assert "## Frame: Other" in content.markdown
        assert f"Source: <{origin}/other>" in content.markdown
        assert "# Other page" in content.markdown
        assert not content.limitations
