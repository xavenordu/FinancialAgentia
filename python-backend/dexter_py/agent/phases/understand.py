import asyncio
import json
import logging
from typing import Optional, Any, AsyncGenerator

from ...model.llm import call_llm_stream
from ..schemas import Understanding

logger = logging.getLogger(__name__)


class UnderstandPhase:
    """
    Production-grade Understanding Phase with:
      - brace-aware JSON extraction
      - timeout on LLM streaming
      - strict JSON-only prompting
      - structured logging
      - partial recovery for malformed output
    """

    STREAM_TIMEOUT = 12  # seconds
    MIN_VALID_JSON_LENGTH = 6  # "{}" + minimal content

    def __init__(self, model: str) -> None:
        self.model = model

    async def run(
        self,
        *,
        query: str,
        conversation_history: Optional[Any] = None
    ) -> Understanding:
        """
        Run the understanding phase and return a parsed Understanding object.
        More robust than naive concatenation and regex extraction.
        """

        try:
            collected = await self._collect_stream_output(
                query=query,
                conversation_history=conversation_history
            )
        except asyncio.TimeoutError:
            logger.warning("UnderstandingPhase timed out during streaming")
            return Understanding(intent=query, entities=[])

        try:
            json_text = self._extract_balanced_json(collected)
            if not json_text:
                raise ValueError("No balanced JSON found in output")

            return Understanding.parse_raw(json_text)

        except Exception as exc:
            logger.error("UnderstandingPhase failed to parse JSON: %s", exc)
            # Attempt partial recovery (extract intent heuristically)
            cleaned_intent = query.strip()
            return Understanding(intent=cleaned_intent, entities=[])

    async def stream(
        self,
        *,
        query: str,
        conversation_history: Optional[Any] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM output token-by-token with timeout guard.
        """

        system_prompt, user_prompt = self._build_prompts(query, conversation_history)

        try:
            async with asyncio.timeout(self.STREAM_TIMEOUT):
                async for token in call_llm_stream(
                    prompt=user_prompt,
                    model=self.model,
                    system_prompt=system_prompt
                ):
                    yield token
        except asyncio.TimeoutError:
            logger.warning("LLM streaming timed out")
            # Output minimal JSON token stream so run() has something
            yield '{"intent": "%s", "entities": []}' % query.replace('"', "'")
        except Exception as exc:
            logger.error("Error during LLM streaming: %s", exc)
            yield '{"intent": "%s", "entities": []}' % query.replace('"', "'")

    # -------------------------
    # Internal helpers
    # -------------------------

    async def _collect_stream_output(
        self,
        *,
        query: str,
        conversation_history: Optional[Any]
    ) -> str:
        """
        Collect streamed tokens into a single string buffer.
        """
        buffer = []

        async for token in self.stream(query=query, conversation_history=conversation_history):
            # Only append text (ignore None or binary chunks)
            if isinstance(token, str):
                buffer.append(token)

        return "".join(buffer)

    def _build_prompts(self, query: str, conversation_history: Optional[Any]):
        """
        Build system + user prompts with robust fallback.
        """

        context_block = ""

        if conversation_history and hasattr(conversation_history, "get_relevant"):
            try:
                relevant = conversation_history.get_relevant(query)
                if relevant:
                    context_block = relevant
            except Exception as exc:
                logger.warning("Conversation history retrieval failed: %s", exc)

        system_prompt = (
            "You must output ONLY valid minified JSON. "
            "No commentary. No prose. No markdown. "
            "JSON schema: {\"intent\": string, \"entities\": array of strings}."
        )

        user_prompt = f"""
Extract the user's intent and entities from this query.
Output only JSON.

Query: "{query}"

Context:
{context_block}

Respond strictly with JSON.
""".strip()

        return system_prompt, user_prompt

    def _extract_balanced_json(self, text: str) -> Optional[str]:
        """
        Extract the first balanced JSON object from stream output using brace counting.
        More reliable than regex for incremental or noisy LLM output.
        """

        start = text.find("{")
        if start == -1:
            return None

        brace_count = 0
        in_string = False
        escape = False

        for i in range(start, len(text)):
            char = text[i]

            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        candidate = text[start : i + 1]
                        if len(candidate) >= self.MIN_VALID_JSON_LENGTH:
                            return candidate
                        else:
                            return None

        return None
