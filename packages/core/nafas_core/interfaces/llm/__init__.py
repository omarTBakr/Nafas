"""The language model port.

The shape is Claude's Messages API on purpose: the plan commits to Claude, and a
narrower home-made shape would only hide features (tools, caching, thinking)
the agent loops need. What the Protocol buys is testability — code under test
gets a FakeLLM that replays scripted responses instead of calling the API.
"""

from nafas_core.interfaces.llm.base import LLM
from nafas_core.interfaces.llm.factory import get_llm

__all__ = ["LLM", "get_llm"]
