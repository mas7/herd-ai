"""CrewAI-specific helpers used to keep tool-driven agents deterministic."""
from __future__ import annotations

from typing import Any

from crewai.llms.base_llm import BaseLLM


class ToolOnlyLLM(BaseLLM):
    """
    Minimal local LLM shim for single-tool CrewAI agents.

    CrewAI eagerly instantiates a provider-backed default LLM when ``Agent.llm``
    is omitted. This shim keeps deterministic, tool-only agents constructible
    and executable in environments without model credentials.
    """

    def __init__(self) -> None:
        super().__init__(model="tool-only", provider="custom")

    def supports_function_calling(self) -> bool:
        return False

    def call(
        self,
        messages: str | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any | None = None,
        from_agent: Any | None = None,
        response_model: type[Any] | None = None,
    ) -> str:
        del tools, callbacks, available_functions, from_task, response_model

        tool_name = _first_tool_name(from_agent)
        return (
            "Thought: I should use the available tool\n"
            f"Action: {tool_name}\n"
            "Action Input: {}"
        )


def _first_tool_name(agent: Any | None) -> str:
    if agent is None or not getattr(agent, "tools", None):
        raise RuntimeError("ToolOnlyLLM requires an agent with exactly one tool")
    return str(agent.tools[0].name)
