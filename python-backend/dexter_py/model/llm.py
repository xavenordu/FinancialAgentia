"""A minimal Python port of the TypeScript LLM wrapper (model/llm.ts).

This implements a best-effort mapping using python-langchain's ChatOpenAI model.
It intentionally supports OpenAI by default; other providers may be added later.
"""
import os
import asyncio
import json
from typing import Optional, Any, AsyncGenerator, Type
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_not_exception_type
from openai import RateLimitError
import pybreaker

# Try to import langchain; if not available, we'll raise a helpful error at runtime.
try:
    from langchain_openai import ChatOpenAI
    # Optional providers - may not be present in all langchain installs
    try:
        from langchain_anthropic import ChatAnthropic  # type: ignore
    except Exception:
        ChatAnthropic = None  # type: ignore
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
    except Exception:
        ChatGoogleGenerativeAI = None  # type: ignore
    try:
        from langchain_ollama import ChatOllama  # type: ignore
    except Exception:
        ChatOllama = None  # type: ignore
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError:
    pass
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "ollama-gpt-oss:120b-cloud"
DEFAULT_SYSTEM_PROMPT = (
    "You are FinancialAgentia, an autonomous financial research agent.\n"
    "Your primary objective is to conduct deep and thorough research on stocks and companies to answer user queries.\n"
    "You are equipped with a set of powerful tools to gather and analyze financial data.\n"
    "You should be methodical, breaking down complex questions into manageable steps and using your tools strategically to find the answers.\n"
    "Always aim to provide accurate, comprehensive, and well-structured information to the user."
)


import os

def get_chat_model(model_name: str = DEFAULT_MODEL, streaming: bool = False):
    """
    Return a chat model instance. Supports Ollama (local/cloud), Anthropic, OpenAI,
    and can be extended for other providers.
    
    Raises RuntimeError if required API keys are missing.
    """
    # --- Ensure OpenAI is available ---
    if ChatOpenAI is None:
        raise RuntimeError("langchain is required for the Python backend. Install from requirements.txt")

    # --- Define provider factories ---
    providers = {}

    # Ollama
    if 'ChatOllama' in globals() and ChatOllama is not None and model_name.startswith("ollama-"):
        is_cloud = model_name.endswith("-cloud")
        base_url = os.getenv("OLLAMA_BASE_URL", "https://ollama.com" if is_cloud else "http://localhost:11434")
        api_key = os.getenv("OLLAMA_API_KEY") if is_cloud else None
        model_clean = model_name.replace("ollama-", "")
        return ChatOllama(model=model_clean, base_url=base_url, api_key=api_key, streaming=streaming)

    # Anthropic
    if 'ChatAnthropic' in globals() and ChatAnthropic is not None and model_name.startswith("claude-"):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
        return ChatAnthropic(model=model_name, streaming=streaming, anthropic_api_key=api_key)

    # Google (optional, only if installed)
    if 'ChatGoogleGenerativeAI' in globals() and ChatGoogleGenerativeAI is not None and model_name.startswith("gemini-"):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not set in environment")
        return ChatGoogleGenerativeAI(model=model_name, streaming=streaming, api_key=api_key)

    # Fallback to OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")
    return ChatOpenAI(model_name=model_name, openai_api_key=api_key, streaming=streaming)

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
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        # Use invoke for non-streaming
        result = chat.invoke(messages)
        return result

    # Add retries and a circuit breaker around provider calls to improve resilience
    breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=30)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), retry=retry_if_not_exception_type(RateLimitError))
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
        return output_model.model_validate(parsed)

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
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            stream = await asyncio.to_thread(lambda: chat.stream(messages))
            for chunk in stream:
                # Each chunk may be a message-like object
                try:
                    if hasattr(chunk, 'content'):
                        yield chunk.content
                    else:
                        yield str(chunk)
                except AttributeError:
                    yield f"Chunk error: {type(chunk)} {chunk}"
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

