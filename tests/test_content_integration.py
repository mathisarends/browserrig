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
            "Closed summary\n\nClosed details secret",
            "Open summary\n\nOpen details text",
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
        assert any("offset=" in item for item in content.limitations)
        assert "Extraction limitations" in content.render()
        assert site in content.render()


async def test_offset_reads_a_long_page_in_parts_without_losing_lines(site):
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(
            tab,
            "document.body.innerHTML = [...Array(60).keys()]"
            ".map(i => `<p>Paragraph ${i} ${'y'.repeat(30)}</p>`).join('')",
        )
        offset, seen, parts = 0, set(), 0
        while True:
            content = await extract_content(tab, max_chars=500, offset=offset)
            parts += 1
            seen.update(re.findall(r"Paragraph \d+ y{30}", content.markdown))
            following = [
                int(match)
                for item in content.limitations
                for match in re.findall(r"offset=(\d+)", item)
            ]
            if not following:
                break
            assert following[0] > offset
            offset = following[0]
        assert parts > 3
        assert seen == {f"Paragraph {index} {'y' * 30}" for index in range(60)}
        assert f"(continued from offset {offset})" in content.render()


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


async def test_spanned_table_cells_fill_every_row_and_column_they_cover(site):
    markup = """<table><tr><th rowspan=2>Name</th>
        <th colspan=2>Height<sup><a href='#n1'>[1]</a></sup></th></tr>
        <tr><th>m</th><th>ft</th></tr>
        <tr><td colspan=3>Asia</td></tr>
        <tr><td>Tower</td><td rowspan=2>828</td><td>2717</td></tr>
        <tr><td>Twin</td><td>2716</td></tr></table>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        text = (await extract_content(tab)).markdown
    assert text.splitlines() == [
        "| Name | Height | Height |",
        "| --- | --- | --- |",
        "| Name | m | ft |",
        "| Asia | | |",
        "| Tower | 828 | 2717 |",
        "| Twin | 828 | 2716 |",
    ]


async def test_grid_layouts_with_aria_table_roles_read_as_tables(site):
    markup = """<div role=table><div role=rowgroup>
        <div role=row><div role=cell>Feature</div><div role=columnheader>Free</div>
        <div role=columnheader>Pro</div></div></div>
        <div role=rowgroup><div role=row><div role=cell>Seats</div><div role=cell>2</div>
        <div role=cell><span>Unlimited</span></div></div>
        <div role=row><div role=cell aria-colspan=3>Security</div></div>
        <div role=row><div role=rowheader>SSO</div><div role=cell>No</div>
        <div role=cell>Yes</div></div></div></div>
        <div role=grid><p>Grid without rows</p></div>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        text = (await extract_content(tab)).markdown
    assert text.splitlines() == [
        "| Feature | Free | Pro |",
        "| --- | --- | --- |",
        "| Seats | 2 | Unlimited |",
        "| Security | | |",
        "| SSO | No | Yes |",
        "",
        "Grid without rows",
    ]


async def test_layout_tables_read_as_text_and_data_tables_stay_tables(site):
    markup = """<table><tr><td>
        <table><tr><td><a href='/item'>Story title</a> (example.org)</td></tr>
        <tr><td>12 points by someone</td></tr></table>
        </td></tr><tr><td><p>First comment</p><p>Second paragraph</p></td></tr></table>
        <table><tr><td>Plan</td><td>Price</td></tr><tr><td>Free</td><td>$0</td></tr>
        <tr><td>Pro</td><td>$10</td></tr><tr><td>Team</td><td>$20</td></tr>
        <tr><td>Enterprise</td><td>Custom</td></tr><tr><td>Edu</td><td>$5</td></tr></table>
        <table><tr><th>Name</th></tr><tr><td>Ada</td></tr></table>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        text = (await extract_content(tab)).markdown
    assert text.splitlines() == [
        "[Story title](</item>) (example.org)",
        "",
        "12 points by someone",
        "",
        "First comment",
        "",
        "Second paragraph",
        "",
        "| | |",
        "| --- | --- |",
        "| Plan | Price |",
        "| Free | $0 |",
        "| Pro | $10 |",
        "| Team | $20 |",
        "| Enterprise | Custom |",
        "| Edu | $5 |",
        "",
        "| Name |",
        "| --- |",
        "| Ada |",
    ]


async def test_collapsed_menus_and_site_chrome_are_left_out_without_main_landmark(site):
    article = "word " * 80
    markup = f"""<header><a href='/login'>Sign in</a>
        <div style='height:0;overflow:clip'><a href='/menu'>Mega menu entry</a></div></header>
        <nav><a href='/news'>News</a></nav>
        <div><h1>Pricing</h1><p>{article}</p>
        <div style='height:0;overflow:hidden'>Closed panel</div>
        <article><header>Plan header</header><p>Plan text</p></article></div>
        <footer>Imprint</footer>"""
    async with ChromeBrowser(LaunchBrowser(url=site)) as browser:
        tab = browser.active_tab
        await evaluate(tab, f"document.body.innerHTML = {json.dumps(markup)}")
        await wait_for_page(tab)
        content = await extract_content(tab)
        full = await extract_content(tab, full_page=True)
    assert "# Pricing" in content.markdown and "Plan header" in content.markdown
    for chrome in ("Sign in", "News", "Imprint"):
        assert chrome not in content.markdown and chrome in full.markdown
    assert "Mega menu entry" not in full.markdown and "Closed panel" not in full.markdown
    assert any("full_page=true" in item for item in content.limitations)
    assert not any("full_page=true" in item for item in full.limitations)
