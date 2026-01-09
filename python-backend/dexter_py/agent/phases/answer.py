from typing import Any, AsyncGenerator
from ...model.llm import call_llm_stream
import json
import re
import os


class AnswerPhase:
    def __init__(self, model: str, context_manager: Any) -> None:
        self.model = model
        self.context_manager = context_manager

    async def run(self, *, query: str, completed_plans: list, task_results: dict) -> AsyncGenerator[str, None]:
        """Generate streaming answer using the LLM."""
        # Build context from plans and results
        context = self._build_context(completed_plans, task_results)
        
        # Check for file paths in query and analyze them
        file_analyses = self._analyze_files_in_query(query)
        if file_analyses:
            context += "\n\nFile Analyses:\n" + "\n".join(file_analyses)
        
        # Import tools here to avoid import issues
        try:
            from ..file_reader import file_reader_tool
            TOOLS = [file_reader_tool]
        except ImportError:
            TOOLS = []
        
        # Build system prompt with tools
        system_prompt = "You are FinancialAgentia, an AI assistant specialized in deep financial research and analysis. You provide expert insights on financial markets, company fundamentals, investment opportunities, and economic trends."
        if TOOLS:
            tool_descs = []
            for t in TOOLS:
                desc = getattr(t, 'description', str(t))
                tool_descs.append(f"- {desc}")
            system_prompt += "\n\nAvailable tools:\n" + "\n".join(tool_descs)
            system_prompt += "\n\nWhen you need to access files or perform analyses, use the available tools by describing what you need."
        
        prompt = f"Query: {query}\n\nContext from research:\n{context}\n\nProvide a comprehensive answer based on the research conducted."

        # Stream the response
        async for token in call_llm_stream(prompt, model=self.model, system_prompt=system_prompt):
            yield token

    def _analyze_files_in_query(self, query: str) -> list[str]:
        """Detect file paths in query and analyze them."""
        # Simple regex for file paths (basic detection)
        path_patterns = [
            r'"([^"]+\.(?:csv|txt))"',  # Quoted paths
            r"'([^']+\.(?:csv|txt))'",  # Single quoted
            r'([C-Z]:[^\s]+\.(?:csv|txt))',  # Windows absolute paths
            r'(/[^\s]+\.(?:csv|txt))',  # Unix absolute paths
        ]
        
        file_paths = []
        for pattern in path_patterns:
            matches = re.findall(pattern, query)
            file_paths.extend(matches)
        
        analyses = []
        for path in file_paths:
            try:
                from ..file_reader import file_reader_tool
                analysis = file_reader_tool.analyze_file(path, 'basic')
                if 'error' not in analysis:
                    analyses.append(f"Analysis of {path}:\n{json.dumps(analysis, indent=2)}")
                else:
                    analyses.append(f"Failed to analyze {path}: {analysis['error']}")
            except Exception as e:
                analyses.append(f"Error analyzing {path}: {str(e)}")
        
        return analyses

    def _build_context(self, completed_plans: list, task_results: dict) -> str:
        """Build context string from plans and results."""
        context_parts = []

        if completed_plans:
            context_parts.append("Completed Plans:")
            for plan in completed_plans:
                context_parts.append(f"- {plan}")

        if task_results:
            context_parts.append("\nTask Results:")
            for task, result in task_results.items():
                context_parts.append(f"- {task}: {result}")

        return "\n".join(context_parts) if context_parts else "No additional context available."
