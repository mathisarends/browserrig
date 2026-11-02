import pytest
from harnessed import ToolCall

from tests.test_secrets_integration import PASSWORD, _agent, _model, _ref, _replies

pytestmark = pytest.mark.integration


async def test_agent_cannot_install_a_secret_listener_before_typing(site):
    holder = {}
    code = (
        "document.addEventListener('input', e => {"
        "document.title = Array.from(e.target.value, c => c.charCodeAt(0)).join('-')"
        "}); 'listener installed'"
    )
    model = _model(
        [
            lambda _state, _request: ToolCall("execute_javascript", {"code": code}),
            lambda state, _request: ToolCall(
                "type_text", {"ref": _ref(state, "Email"), "text": "{{secret:pw}}"}
            ),
            lambda _state, _request: "Done",
        ]
    )
    async with _agent(site, model, (site,), holder).session() as session:
        await session.run("Log in", max_steps=4)
    replies = _replies(model)
    assert replies[0].is_error
    assert not replies[1].is_error
    encoded = "-".join(str(ord(character)) for character in PASSWORD)
    assert encoded not in repr(model.requests[-1].messages)
