"""A minimal Python port of the TypeScript LLM wrapper (model/llm.ts).

This implements a best-effort mapping using python-langchain's ChatOpenAI model.
It intentionally supports OpenAI by default; other providers may be added later.
"""
import os
import asyncio
import json
from typing import Optional, Any, AsyncGenerator, Type
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import pybreaker

# Try to import langchain; if not available, we'll raise a helpful error at runtime.
try:
    from langchain.chat_models import ChatOpenAI
    # Optional providers - may not be present in all langchain installs
    try:
        from langchain.chat_models import ChatAnthropic  # type: ignore
    except Exception:
        ChatAnthropic = None  # type: ignore
    try:
        from langchain.chat_models import ChatGoogleGenerativeAI  # type: ignore
    except Exception:
        ChatGoogleGenerativeAI = None  # type: ignore
    from langchain.schema import HumanMessage, SystemMessage
except Exception:
    ChatOpenAI = None  # type: ignore

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."


def get_chat_model(model_name: str = DEFAULT_MODEL, streaming: bool = False):
    """Return a chat model instance. For now we support OpenAI via langchain.

    Raises a RuntimeError if langchain is not installed or API key missing.
    """
    if ChatOpenAI is None:
        raise RuntimeError("langchain is required for the Python backend. Install from requirements.txt")

    # Provider mapping by model name prefix (matches TypeScript mapping)
    def default_factory(name: str, streaming_flag: bool):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment")
        return ChatOpenAI(model_name=name, streaming=streaming_flag, openai_api_key=api_key)

    providers = {}
    if 'ChatAnthropic' in globals() and ChatAnthropic is not None:
        providers['claude-'] = lambda name, s: ChatAnthropic(model=name, streaming=s, anthropic_api_key=os.getenv('ANTHROPIC_API_KEY'))
    if 'ChatGoogleGenerativeAI' in globals() and ChatGoogleGenerativeAI is not None:
        providers['gemini-'] = lambda name, s: ChatGoogleGenerativeAI(model=name, streaming=s, api_key=os.getenv('GOOGLE_API_KEY'))

    prefix = None
    for p in providers.keys():
        if model_name.startswith(p):
            prefix = p
            break

    if prefix:
        factory = providers[prefix]
        return factory(model_name, streaming)

    # Fallback to OpenAI
    return default_factory(model_name, streaming)


async def call_llm(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    output_model: Optional[Type[Any]] = None,
    tools: Optional[list] = None,
) -> Any:
    """Call the chat model and return either a raw string or parsed structured output.

    output_model: if provided, should be a pydantic BaseModel class. The function
    expects the LLM to return JSON that matches the model and will parse it.

    tools: optional list of tool descriptors - if provided we include their
    descriptions in the system prompt to help the model call/mention them.
    """
    model_name = model or DEFAULT_MODEL
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # If tools provided, append a tools section to the system prompt so the LLM
    # can reference available tools (best-effort binding support).
    if tools:
        tool_descs = []
        for t in tools:
            # Try to get a helpful string description
            try:
                desc = getattr(t, 'description', str(t))
            except Exception:
                desc = str(t)
            tool_descs.append(f"- {desc}")
        system_prompt = system_prompt + "\n\nAvailable tools:\n" + "\n".join(tool_descs)

    chat = get_chat_model(model_name, streaming=False)

    def _sync_call():
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=prompt)]
        # Try predict_messages (returns message object), else predict (string)
        if hasattr(chat, 'predict_messages'):
            try:
                return chat.predict_messages(messages)
            except Exception:
                pass
        if hasattr(chat, 'predict'):
            return chat.predict(prompt)
        # Fallback to calling generate / create
        if hasattr(chat, 'generate'):
            # generate returns a Generation object; try to extract text
            gen = chat.generate(messages)
            try:
                # Attempt to pull combined text
                return ' '.join([c.output_text for r in gen.generations for c in r])
            except Exception:
                return str(gen)
        raise RuntimeError('No supported call method on chat model')

    # Add retries and a circuit breaker around provider calls to improve resilience
    breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=30)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), retry=retry_if_exception_type(Exception))
    def _resilient_sync_call():
        # Use the circuit breaker to call the provider; pybreaker will raise on open circuit
        return breaker.call(_sync_call)

    result = await asyncio.to_thread(_resilient_sync_call)

    # Extract text content if it's a message-like object
    content: str
    if hasattr(result, 'content'):
        content = result.content
    else:
        content = str(result)

    # If an output_model (pydantic) is provided, expect JSON and parse it
    if output_model is not None:
        try:
            parsed = json.loads(content)
        except Exception:
            # Try to extract JSON substring from content
            try:
                start = content.index('{')
                end = content.rindex('}') + 1
                parsed = json.loads(content[start:end])
            except Exception as e:
                raise RuntimeError(f'Failed to parse JSON from model output: {e}\nOutput was: {content}')
        # Use pydantic to validate/construct
        return output_model.parse_obj(parsed)

    return content


async def call_llm_stream(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Async generator that yields pieces of text from the model.

    If the selected chat model supports streaming via langchain, this will
    attempt to use it. Otherwise it will yield the full response as a single
    chunk.
    """
    model_name = model or DEFAULT_MODEL
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    chat = get_chat_model(model_name, streaming=True)

    # If the chat model exposes a stream API, use it. Otherwise fall back.
    if hasattr(chat, 'stream'):
        # Best-effort: langchain stream APIs vary; attempt a common pattern
        try:
            # Wrap the stream creation in a small resilient wrapper
            breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=30)

            @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), retry=retry_if_exception_type(Exception))
            def _get_stream():
                return breaker.call(lambda: chat.stream([SystemMessage(content=system_prompt), HumanMessage(content=prompt)]))

            stream = await asyncio.to_thread(_get_stream)
            for chunk in stream:
                # Each chunk may be a message-like object
                if hasattr(chunk, 'content'):
                    yield chunk.content
                else:
                    yield str(chunk)
            return
        except Exception:
            # Fall through to single-chunk fallback
            pass

    # Fallback: non-streaming call, yield once
    full = await call_llm(prompt, model=model_name, system_prompt=system_prompt)
    if isinstance(full, str):
        yield full
    else:
        # If parsed object, convert to string form
        yield str(full)

