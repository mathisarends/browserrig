import importlib
import sys

import pytest
from harnessed import Agent, SessionState
from harnessed.testing import ScriptedModel


@pytest.mark.parametrize("save_state", [False, True])
async def test_example_persists_and_continues_only_with_explicit_state_file(
    monkeypatch, tmp_path, capsys, save_state
):
    pytest.importorskip("pydantic_ai.models.openai")
    example = importlib.import_module("examples.openai_agent")
    model = ScriptedModel(["First answer", "Second answer"])
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    monkeypatch.chdir(tmp_path)
    # Exercise real Harnessed state and example file I/O without Chrome or API calls.
    monkeypatch.setattr(example, "OpenAIResponsesModel", lambda _name: model)
    monkeypatch.setattr(example, "PydanticAIModel", lambda native: native)
    monkeypatch.setattr(example, "BrowserAgent", lambda **config: Agent(model=config["model"]))
    state_file = tmp_path / "conversation" / "state.json"
    state_args = ["--state", str(state_file)] if save_state else []
    for prompt in ("Remember the first task", "Continue the task"):
        monkeypatch.setattr(sys, "argv", ["example", "--task", prompt, "--quiet", *state_args])
        await example.main()
    assert capsys.readouterr().out.splitlines() == ["First answer", "Second answer"]
    assert ("First answer" in repr(model.requests[-1].messages)) is save_state
    if save_state:
        state = SessionState.from_json(state_file.read_text(encoding="utf-8"))
        assert "Second answer" in state.to_json()
        assert not state_file.with_suffix(".json.tmp").exists()
    else:
        assert not list(tmp_path.iterdir())
