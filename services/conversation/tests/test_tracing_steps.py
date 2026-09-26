"""With tracing on, a patient's message is one trace: each pipeline step nested in it, with data for inputs."""

from unittest.mock import MagicMock

import langsmith
from langsmith.run_helpers import tracing_context

from nafas_core.interfaces.llm.fake import FakeLLM, text_message

from .test_medical import ask, classified, guarded, scoped, sensitivity


async def test_a_medical_question_is_one_trace_with_every_gate_in_it():
    runs = []
    client = MagicMock(spec=langsmith.Client)
    client.create_run.side_effect = lambda **run: runs.append(run)
    llm = FakeLLM(
        [classified("medical"), scoped("in_scope"), sensitivity(False), text_message("حوالي ١٢٠ على ٨٠."), guarded("pass")]
    )

    with tracing_context(enabled=True, client=client, project_name="nafas-test"):
        turn = await ask(llm, "هو الضغط الطبيعي كام؟")

    assert turn.reply.text == "حوالي ١٢٠ على ٨٠."
    names = [r["name"] for r in runs]
    for step in (
        "conversation.turn",
        "conversation.intent",
        "conversation.medical",
        "gate.scope",
        "gate.sensitivity",
        "gate.output_guard",
    ):
        assert step in names, f"{step} was not traced"
    # one trace: every run shares the turn's trace id
    assert len({r["trace_id"] for r in runs}) == 1
    turn_run = next(r for r in runs if r["name"] == "conversation.turn")
    assert turn_run["inputs"]["history"] == [{"role": "user", "content": "هو الضغط الطبيعي كام؟"}]
    # clients and models are not data: they stay out of the trace
    assert all("llm" not in r["inputs"] and "identity" not in r["inputs"] for r in runs)
