import json
import re

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
        snapshot = await capture(tab, DomMode(sparse_text_chars=0), report)
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
            "[Details](</other?q=1&x=2>)",
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
        await (await tab.main_frame()).run_on_node(
            button.backend_id,
            ELEMENT,
            ElementArgs(operation=ElementOperation.POINT, value=False),
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


@pytest.mark.parametrize("article_chars", [400, 20])
async def test_main_region_replaces_page_chrome_unless_it_holds_too_little(site, article_chars):
    markup = (
        "<header><a href='/login'>Sign in</a></header><nav><a href='/news'>News</a></nav>"
        f"<main><h1>Article</h1><p>{'word ' * (article_chars // 5)}</p></main>"
        "<footer>Imprint</footer>"
    )
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        content = await extract_content(tab)
        full = await extract_content(tab, full_page=True)
    assert "# Article" in content.markdown and "Imprint" in full.markdown
    assert not any("main region" in item for item in full.limitations)
    if article_chars > 200:
        assert "Sign in" not in content.markdown and "Imprint" not in content.markdown
        assert any("full_page=true" in item for item in content.limitations)
    else:
        # A main landmark with almost no text is not trusted to hold the content.
        assert content.markdown == full.markdown


async def test_links_are_compact_and_controls_are_left_to_observe(site):
    markup = """<h1>Links</h1>
        <p><a href='#part'>Jump</a> <a href='/'>This page</a> <a href='/other#top'>Other</a>
        <a href='https://example.org/a?b=1'>External</a></p>
        <ul><li><a href='/item'><img alt='Item preview'></a>
        <a href='/item'>Item title</a></li></ul>
        <p>Before <button>Hide</button> after</p>
        <h3><button aria-expanded=false>Question?</button></h3>
        <label><input type=radio name=size>Small</label>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        text = (await extract_content(tab)).markdown
    assert "Jump This page [Other](</other#top>)" in text
    assert "[External](<https://example.org/a?b=1>)" in text
    assert "[Item preview](</item>) Item title" in text
    assert "Before after" in text and "### Question?" in text
    assert "Hide" not in text and "Small" not in text
    assert not re.search(r"[ \t]+$", text, flags=re.M)


async def test_search_results_and_cards_read_as_compact_list_items(site):
    markup = """<h2><span></span></h2><ol><li></li>
        <li><h2><a href='https://www.google.com/url?q=https://docs.example.org/a&amp;sa=U'>
        Result</a></h2></li>
        <li><a href='/card'><h3>Card title</h3><p>Card text</p></a></li></ol>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        text = (await extract_content(tab)).markdown
    assert text.splitlines()[:2] == [
        "1. ## [Result](<https://docs.example.org/a>)",
        "2. [Card title · Card text](</card>)",
    ]


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
