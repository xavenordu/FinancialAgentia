from typing import Optional, Any
from dexter_py.model.llm import call_llm
from dexter_py.agent import schemas
from dexter_py.agent.schemas import Understanding


class UnderstandPhase:
    """Ported UnderstandPhase: extracts intent and entities using the LLM.

    This implementation mirrors the TypeScript behavior: it builds a system
    prompt, optionally includes conversation context, and asks the model to
    return a structured JSON matching `Understanding`.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    async def run(self, *, query: str, conversation_history: Optional[Any] = None) -> Understanding:
        # Build conversation context if available
        conversation_context: Optional[str] = None
        if conversation_history is not None:
            # Best-effort compatibility with the TS MessageHistory API
            try:
                if hasattr(conversation_history, 'hasMessages') and conversation_history.hasMessages():
                    relevant = await conversation_history.selectRelevantMessages(query)
                    if relevant and hasattr(conversation_history, 'formatForPlanning'):
                        conversation_context = conversation_history.formatForPlanning(relevant)
            except Exception:
                # Fallback: ignore conversation history if methods differ
                pass

        # Import prompts lazily to avoid circular imports at module load
        from dexter_py.agent import prompts as _prompts

        system_prompt = _prompts.getUnderstandSystemPrompt()
        user_prompt = _prompts.buildUnderstandUserPrompt(query, conversation_context)

        # Call LLM with structured output (pydantic model)
        result = await call_llm(user_prompt, model=self.model, system_prompt=system_prompt, output_model=schemas.Understanding)

        # call_llm returns a pydantic model instance when output_model is provided
        if isinstance(result, Understanding):
            return result

        # If for some reason it's a dict-like, coerce to the model
        return Understanding.parse_obj(result)
