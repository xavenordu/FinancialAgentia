from typing import Any, List


class ToolExecutor:
    def __init__(self, *, tools: List[Any], context_manager: Any) -> None:
        self.tools = tools
        self.context_manager = context_manager

    async def execute_tool(self, tool_name: str, args: dict) -> dict:
        # Minimal stub: pretend tool ran and returned args
        return {"tool": tool_name, "result": args}
