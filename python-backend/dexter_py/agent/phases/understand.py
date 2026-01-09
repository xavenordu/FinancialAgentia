from typing import Optional, Any, AsyncGenerator
from ...model.llm import call_llm_stream
from .. import schemas
from ..schemas import Understanding
import json
import re


class UnderstandPhase:
    """
    UnderstandPhase (streaming): extracts intent and entities from a user query using the LLM,
    with streaming support for partial processing.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    async def run(
        self,
        *,
        query: str,
        conversation_history: Optional[Any] = None
    ) -> Understanding:
        """
        Run the understanding phase and return the final Understanding object.
        """
        # Collect streaming chunks into a buffer
        collected_output = ""
        async for chunk in self.stream(query=query, conversation_history=conversation_history):
            collected_output += chunk

        # Attempt to parse final JSON output from LLM
        try:
            # Clean up output in case LLM adds extraneous text
            json_text = self._extract_json(collected_output)
            return Understanding.parse_raw(json_text)
        except Exception:
            # Fallback to minimal understanding
            return Understanding(intent=query, entities=[])

    async def stream(
        self,
        *,
        query: str,
        conversation_history: Optional[Any] = None
    ) -> AsyncGenerator[str, None]:
        """
        Streaming version: yields LLM tokens as they arrive.
        """
        # ----------------------------
        # 1. Build conversation context
        # ----------------------------
        conversation_context: Optional[str] = None
        if conversation_history:
            try:
                has_messages = getattr(conversation_history, "hasMessages", lambda: False)()
                if has_messages:
                    select_relevant = getattr(conversation_history, "selectRelevantMessages", None)
                    if callable(select_relevant):
                        relevant = await select_relevant(query)
                        if relevant:
                            format_for_planning = getattr(conversation_history, "formatForPlanning", None)
                            if callable(format_for_planning):
                                conversation_context = format_for_planning(relevant)
            except Exception:
                pass

        # ----------------------------
        # 2. Build prompts
        # ----------------------------
        try:
            from .. import prompts as _prompts
            system_prompt = _prompts.getUnderstandSystemPrompt()
            user_prompt = _prompts.buildUnderstandUserPrompt(query, conversation_context)
        except Exception:
            system_prompt = "You are a financial research agent. Extract user intent and entities."
            user_prompt = f"Analyze the query: {query}"

        # ----------------------------
        # 3. Stream LLM output
        # ----------------------------
        try:
            async for token in call_llm_stream(prompt=user_prompt, model=self.model, system_prompt=system_prompt):
                yield token
        except Exception:
            # Fallback: yield the query as intent
            yield json.dumps({"intent": query, "entities": []})

    def _extract_json(self, text: str) -> str:
        """
        Attempt to extract the first JSON object from the LLM output.
        """
        json_pattern = re.compile(r"\{.*\}", re.DOTALL)
        match = json_pattern.search(text)
        if match:
            return match.group(0)
        # Fallback: return minimal JSON
        return json.dumps({"intent": text.strip(), "entities": []})
