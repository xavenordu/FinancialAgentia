import asyncio
from typing import Any, AsyncGenerator, Iterable
from ...model.llm import call_llm_stream
import json
import re


class AnswerPhase:
    """Generate LLM answers by combining query input, plan outputs, and file analysis."""

    # Patterns compiled once for efficiency
    _PATH_PATTERNS = [
        re.compile(r'"([^"]+\.(?:csv|txt))"'),
        re.compile(r"'([^']+\.(?:csv|txt))'"),
        re.compile(r'([A-Za-z]:[^\s]+\.(?:csv|txt))'),
        re.compile(r'(/[^\s]+\.(?:csv|txt))'),
    ]

    def __init__(self, model: str, context_manager: Any) -> None:
        self.model = model
        self.context_manager = context_manager

    async def run(
        self,
        *,
        query: str,
        completed_plans: list,
        task_results: dict,
        message_history: Any = None
    ) -> AsyncGenerator[str, None]:
        """Stream a synthesized answer to the user with optional conversation context.
        
        Args:
            query: The original user query
            completed_plans: List of completed plans from execution
            task_results: Results from all executed tasks
            message_history: Optional MessageHistory for multi-turn context
        """
        
        context = self._build_context(completed_plans, task_results)

        # Add conversation context if available
        conversation_context = ""
        if message_history and hasattr(message_history, 'has_messages'):
            if message_history.has_messages():
                conversation_context = message_history.format_for_planning()

        # Safely analyze file references
        file_analyses = self._analyze_files_in_query(query)
        if file_analyses:
            context += "\n\nFile Analyses:\n" + "\n".join(file_analyses)

        system_prompt = self._build_system_prompt()

        # Build prompt with optional conversation context
        prompt_parts = []
        if conversation_context:
            prompt_parts.append(conversation_context)
        
        prompt_parts.extend([
            f"Query: {query}\n\n",
            f"Context from research:\n{context}\n\n",
            "Provide a comprehensive answer based on the research conducted."
        ])
        
        prompt = "".join(prompt_parts)

        # Stream response safely
        async for token in call_llm_stream(
            prompt,
            model=self.model,
            system_prompt=system_prompt
        ):
            yield token

    # ------------------------
    # Internal helper methods
    # ------------------------

    def _build_system_prompt(self) -> str:
        """Construct the system prompt with optional tool descriptions."""

        base_text = (
            "You are FinancialAgentia, an AI assistant specialized in deep financial analysis. "
            "Your role is to interpret research results, evaluate financial data, and synthesize conclusions."
        )

        # Attempt to load tools safely
        tools = self._load_tools()
        if not tools:
            return base_text

        tool_descs = []
        for tool in tools:
            desc = getattr(tool, "description", repr(tool))
            tool_descs.append(f"- {desc}")

        joined = "\n".join(tool_descs)
        return (
            f"{base_text}\n\nAvailable tools:\n{joined}\n\n"
            "Invoke tools by describing the inputs you need them to process."
        )

    def _load_tools(self) -> list:
        """Load optional tools defensively."""
        try:
            from ..file_reader import file_reader_tool
            return [file_reader_tool]
        except Exception:
            return []

    def _analyze_files_in_query(self, query: str) -> list[str]:
        """Detect file paths and analyze them using file_reader_tool if available."""
        
        file_paths = self._extract_paths(query)
        if not file_paths:
            return []

        tools = self._load_tools()
        if not tools:
            return [f"File references detected but no file tools are available."]

        results = []
        file_reader_tool = tools[0]

        for path in file_paths:
            try:
                analysis = file_reader_tool.analyze_file(path, "basic")
                if isinstance(analysis, dict) and "error" in analysis:
                    results.append(f"Failed to analyze {path}: {analysis['error']}")
                else:
                    readable = json.dumps(analysis, indent=2)
                    results.append(f"Analysis of {path}:\n{readable}")
            except Exception as exc:
                results.append(f"Error analyzing {path}: {exc}")

        return results

    def _extract_paths(self, text: str) -> list[str]:
        """Extract file paths from text safely and efficiently."""
        found: set[str] = set()
        for pattern in self._PATH_PATTERNS:
            for match in pattern.findall(text):
                if match:
                    found.add(match)
        return list(found)

    def _build_context(self, completed_plans: Iterable[Any], task_results: dict) -> str:
        """Convert completed plan data and task outputs into a readable context block."""
        parts = []

        if completed_plans:
            parts.append("Completed Plans:")
            for plan in completed_plans:
                parts.append(f"- {plan}")

        if task_results:
            parts.append("")
            parts.append("Task Results:")
            for key, value in task_results.items():
                serialized = json.dumps(value, indent=2) if not isinstance(value, str) else value
                parts.append(f"- {key}: {serialized}")

        return "\n".join(parts) if parts else "No additional context available."
    
async def call_llm(
    prompt: str,
    model_name: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
    output_model: Optional[Any] = None,
) -> Any:
    """Robust LLM call with optional tool awareness and structured output."""
    
    model_name = model_name or DEFAULT_MODEL
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Attach tool descriptions
    if tools:
        descs = []
        for t in tools:
            try:
                desc = getattr(t, "description", str(t))
            except Exception:
                desc = str(t)
            descs.append(f"- {desc}")
        system_prompt += "\n\nAvailable tools:\n" + "\n".join(descs)

    # Prepare payload
    request_body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
    }

    # Retry logic (simplified example)
    for attempt in range(3):
        try:
            response = await openai_client.chat.completions.create(**request_body)
            text = response.choices[0].message["content"]
            
            if output_model:
                return output_model.parse_raw(text)
            return text

        except Exception as error:
            if attempt == 2:
                raise
            await asyncio.sleep(0.8 * (attempt + 1))
            try:
                return output_model.parse_raw(content)
            except Exception as parse_exc:
                raise ValueError(f"Failed to parse LLM output: {parse_exc}") from parse_exc 