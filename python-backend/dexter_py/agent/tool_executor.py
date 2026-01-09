from typing import Any, List, Optional, Dict, Callable, Awaitable


class ToolExecutor:
    def __init__(self, *, tools: List[Any], context_manager: Any) -> None:
        """
        tools: a list of tool objects, each expected to have at least a 'name' attribute
               and optionally an async 'run' method taking **kwargs.
        context_manager: abstract dependency injected for stateful tool contexts.
        """
        self.context_manager = context_manager
        self._tool_registry = self._index_tools(tools)

    def _index_tools(self, tools: List[Any]) -> Dict[str, Any]:
        """Indexes tools by their .name attribute."""
        registry = {}

        if not isinstance(tools, list):
            return registry

        for t in tools:
            name = getattr(t, "name", None)
            if isinstance(name, str) and name not in registry:
                registry[name] = t

        return registry

    async def execute_tool(self, tool_name: str, args: Optional[dict]) -> dict:
        """
        Executes a tool by name, if found.

        Behavior:
        - Validates input types
        - Returns predictable error structures
        - Falls back to stub execution if the tool has no run() method
        - Never raises exceptions outward (contained failures)
        """

        # Validate tool_name
        if not isinstance(tool_name, str) or not tool_name.strip():
            return {
                "tool": None,
                "error": "Invalid tool name",
                "failed": True,
            }

        # Safety check args
        if args is None:
            args = {}
        elif not isinstance(args, dict):
            return {
                "tool": tool_name,
                "error": "Arguments must be a dictionary",
                "failed": True,
            }

        tool = self._tool_registry.get(tool_name)

        if tool is None:
            return {
                "tool": tool_name,
                "error": "Tool not found",
                "failed": True,
            }

        # Try real execution if tool has run() method
        try:
            run_method = getattr(tool, "run", None)

            if callable(run_method):
                # If it's an async method, await it
                if hasattr(run_method, "__await__"):
                    result = await run_method(**args)
                else:
                    # Synchronous run method fallback
                    result = run_method(**args)

                return {
                    "tool": tool_name,
                    "result": result,
                }

            # No run method: stub behavior
            return {
                "tool": tool_name,
                "result": {"args": args, "stub": True},
            }

        except Exception as exc:
            # Contain error, return structured failure
            return {
                "tool": tool_name,
                "error": str(exc),
                "failed": True,
            }
