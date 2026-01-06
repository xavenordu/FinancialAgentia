from typing import Any, AsyncGenerator


class AnswerPhase:
    def __init__(self, model: str, context_manager: Any) -> None:
        self.model = model
        self.context_manager = context_manager

    async def run(self, *, query: str, completed_plans: list, task_results: dict) -> AsyncGenerator[str, None]:
        # Minimal streaming answer generator: yield a short answer then finish
        async def gen():
            yield f"Final answer for: {query}"
        # Return the generator itself
        return gen()
