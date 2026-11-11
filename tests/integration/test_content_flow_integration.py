import pytest

from browserrig import ChromeBrowser, DomCapture, Viewport, wait_for_page
from browserrig.browser import Launch
from browserrig.observation import ContentGroup, Snapshot, TextBlock, capture, render
from browserrig.secrets.redaction import Redactor
from tests.javascript import evaluate

pytestmark = pytest.mark.integration


async def test_form_guidance_and_inline_links_stay_between_their_controls(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<main>
            <h1>Fork project</h1><p>A fork is a copy of a project.</p>
            <form aria-label="Fork settings">
              <label>Project name<input value=buck></label>
              <p>Use <strong>small</strong> <em>reusable</em> modules.</p>
              <p>Want a namespace? <a href=/groups/new>Create a group</a> instead.</p>
              <label>Project slug<input value=buck></label>
              <p>Keep this guidance.</p><button>Fork project</button>
            </form><p>Keep this guidance.</p></main>`;""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    text = render(state)
    assert "page text:" not in text
    assert text.index("A fork is a copy") < text.index('textbox "Project name"')
    assert text.index('textbox "Project name"') < text.index(
        "Use small reusable modules."
    )
    assert "text: Want a namespace? [Create a group][" in text
    assert "] instead." in text
    assert text.index("Want a namespace?") < text.index('textbox "Project slug"')
    assert text.count('textbox "Project name"') == 1
    assert "text: Project name" not in text
    assert "text: Fork project" not in text
    assert text.count("Keep this guidance.") == 2
    assert '<form "Fork settings">' in text
    restored = Snapshot.model_validate_json(state.model_dump_json())
    assert render(restored) == text
    assert restored.content == state.content


async def test_prose_keeps_punctuation_paragraphs_and_code_lines(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<main>
            <p>Read <a href=/guide>the guide</a>, then continue.</p>
            <p>Another <a href=/topic>topic</a> here.</p>
            <div role=note>See <a href=/more>more</a>, too.</div>
            <p>Use <a href=/category aria-label="Navigation category">Computers</a> now.</p>
            <pre><span>if ready:</span>\n    <span>run()</span>\n<span>done()</span></pre>
            </main>`;""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    text = render(state)
    guide = next(element for element in state.elements if element.name == "the guide")
    topic = next(element for element in state.elements if element.name == "topic")
    more = next(element for element in state.elements if element.name == "more")
    category = next(
        element for element in state.elements if element.name == "Navigation category"
    )
    assert f"text: Read [the guide][{guide.ref}], then continue." in text
    assert f"text: Another [topic][{topic.ref}] here." in text
    assert f"text: See [more][{more.ref}], too." in text
    assert f"text: Use [Computers][{category.ref}] now." in text
    assert "if ready:\n" in text and "    run()\n" in text
    blocks = list(_text_blocks(state.content or ()))
    assert any(
        block.preformatted and block.text == "if ready:\n    run()\ndone()"
        for block in blocks
    )


async def test_text_budget_marks_the_paragraph_and_keeps_later_controls(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<main><p>
            ${'Long guidance '.repeat(100)}</p><button>Continue</button>
            <p>Later context</p><button>Cancel</button></main>`;""",
        )
        state = await capture(
            tab,
            DomCapture(max_text_chars=80, sparse_text_chars=0),
            await wait_for_page(tab),
        )
    text = render(state)
    assert text.index("[text truncated]") < text.index('button "Continue"')
    assert 'button "Cancel"' in text
    assert len(state.text) <= 80
    blocks = list(_text_blocks(state.content or ()))
    assert sum(len(block.text) for block in blocks) <= 80
    assert any(block.truncated for block in blocks)
    assert any("truncated" in note for note in state.limitations)


async def test_frame_content_is_inserted_at_the_frame_owner(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<main>
            <p>Before embedded form</p>
            <iframe srcdoc="<p>Inside guidance</p><button>Inside action</button>"></iframe>
            <p>After embedded form</p><button>Outside action</button></main>`;""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    text = render(state)
    assert text.index("Before embedded form") < text.index("Inside guidance")
    assert text.index("Inside guidance") < text.index('button "Inside action"')
    assert text.index('button "Inside action"') < text.index("After embedded form")
    assert text.index("After embedded form") < text.index('button "Outside action"')
    inside = next(
        block
        for block in _text_blocks(state.content or ())
        if block.text == "Inside guidance"
    )
    assert inside.bounds is not None and inside.bounds.x >= 8 and inside.bounds.y > 20


async def test_exact_text_budget_boundary_still_reports_the_omitted_next_block(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML =
            '<p>' + 'x'.repeat(79) + '  </p><p>Omitted help</p><button>Continue</button>';""",
        )
        state = await capture(
            tab,
            DomCapture(max_text_chars=80, sparse_text_chars=0),
            await wait_for_page(tab),
        )
    text = render(state)
    assert "[text truncated]" in text and 'button "Continue"' in text
    assert any("truncated" in note for note in state.limitations)


async def test_same_named_groups_keep_their_own_help_and_identity(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<main>
            <fieldset><legend>Account</legend><p>First guidance</p><button>First</button></fieldset>
            <fieldset><legend>Account</legend><p>Second guidance</p>
              <button>Second</button></fieldset>
            </main>`;""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    text = render(state)
    assert text.count('<group "Account">') == 2
    assert (
        text.index("First guidance")
        < text.index('button "First"')
        < text.index("Second guidance")
    )
    assert text.index("Second guidance") < text.index('button "Second"')
    (main,) = state.content or ()
    assert isinstance(main, ContentGroup)
    groups = [node for node in main.children if isinstance(node, ContentGroup)]
    assert len(groups) == 2 and groups[0].id != groups[1].id


async def test_hidden_clipped_and_covered_text_is_omitted_from_the_flow(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `
            <p>Visible guidance</p><p hidden>Hidden guidance</p>
            <p style="opacity:0">Transparent guidance</p>
            <div style="overflow:hidden;width:5px;height:5px">
              <p style="margin-left:100px">Clipped guidance</p></div>
            <div style="position:absolute;left:500px;top:100px;width:300px;height:80px">
              <p>Covered guidance</p>
              <div style="position:absolute;inset:0;background:white"></div></div>`;""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    text = render(state)
    assert "Visible guidance" in text
    assert all(
        value not in text
        for value in (
            "Hidden guidance",
            "Transparent guidance",
            "Clipped guidance",
            "Covered guidance",
        )
    )


async def test_text_preview_uses_the_same_partition_as_its_controls(site):
    async with ChromeBrowser(
        Launch(url=site, viewport=Viewport(width=800, height=600))
    ) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            """document.body.innerHTML = `<style>
            body{margin:0;height:2600px}p,button{position:absolute;left:20px}
            </style><p style="top:500px">Earlier help</p>
            <button style="top:550px">Earlier</button>
            <p style="top:1250px">Current help</p><button style="top:1300px">Current</button>
            <p style="top:2100px">Upcoming help</p><button style="top:2150px">Upcoming</button>`;
            scrollTo(0,1200);""",
        )
        state = await capture(tab, DomCapture(), await wait_for_page(tab))
    text = render(state)
    viewport, rest = text.split("above viewport (preview", 1)
    above, below = rest.split("below viewport (preview", 1)
    assert "Current help" in viewport and "Earlier help" not in viewport
    assert above.index("Earlier help") < above.index('button "Earlier"')
    assert "Upcoming help" not in above
    assert below.index("Upcoming help") < below.index('button "Upcoming"')


async def test_new_text_is_redacted_and_fingerprinted_beyond_legacy_excerpt(site):
    async with ChromeBrowser(Launch(url=site)) as browser:
        tab = browser.active_tab
        await wait_for_page(tab)
        await evaluate(
            tab,
            "document.body.innerHTML = '<button>Repeated label</button>'.repeat(10)"
            " + '<p id=note>Initial guidance</p>'",
        )
        strategy = DomCapture(max_text_chars=80, sparse_text_chars=0)
        report = await wait_for_page(tab)
        before = await capture(tab, strategy, report)
        await evaluate(
            tab,
            "document.querySelector('#note').textContent='Updated guidance token-456'",
        )
        after = await capture(tab, strategy, report)
        assert before.text == after.text and before.fingerprint != after.fingerprint
        redactor = Redactor()
        redactor.add("token", "token-456")
        clean = await capture(tab, strategy, report, redaction=_Redaction(redactor))
    assert "Updated guidance" in render(clean)
    assert "token-456" not in clean.model_dump_json()
    assert "{{secret:token}}" in render(clean)


def _text_blocks(nodes):
    for node in nodes:
        if isinstance(node, ContentGroup):
            yield from _text_blocks(node.children)
        elif isinstance(node, TextBlock):
            yield node


class _Redaction:
    def __init__(self, redactor: Redactor):
        self._redactor = redactor

    def redact(self, value):
        return self._redactor.scrub(value)
