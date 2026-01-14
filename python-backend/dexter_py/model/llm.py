"""A minimal Python port of the TypeScript LLM wrapper (model/llm.ts).

This implements a best-effort mapping using python-langchain's ChatOpenAI model.
It intentionally supports OpenAI by default; other providers may be added later.
"""
import os
import asyncio
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_not_exception_type
from openai import RateLimitError
import pybreaker
from typing import Any, Optional, List, AsyncGenerator, Type, TypeVar
from dataclasses import dataclass
import os
import json
import structlog
from pydantic import BaseModel
T = TypeVar("T", bound=BaseModel)


DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TIMEOUT = 120

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

from ..utils._utils import _classify_error, _build_system_prompt_with_tools, get_llm_client, LLMError, LLMRateLimitError, LLMTimeoutError, LLMParseError
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "ollama-qwen3-coder:480b-cloud" # Local Ollama by default
# DEFAULT_MODEL = "ollama-mistral:70b"  
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
    tools: Optional[List[Any]] = None,
    output_model: Optional[Type[T]] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    **kwargs
) -> Any:
    """
    Call LLM with robust error handling and optional structured output.
    
    Args:
        prompt: User prompt
        model: Model name (uses config default if not provided)
        system_prompt: System prompt (uses config default if not provided)
        tools: Optional list of tools to include in system prompt
        output_model: Optional Pydantic model for structured output
        max_tokens: Max tokens to generate
        temperature: Sampling temperature
        **kwargs: Additional API parameters
        
    Returns:
        String response or parsed output_model instance
        
    Raises:
        LLMError: On API failures after retries
        LLMParseError: If output_model parsing fails
        
    Examples:
        # Simple call
        response = await call_llm("What is 2+2?")
        
        # With structured output
        class Answer(BaseModel):
            result: int
        
        answer = await call_llm(
            "What is 2+2? Respond with JSON.",
            output_model=Answer
        )
        print(answer.result)  # 4
    """
    logger = structlog.get_logger(__name__)
    config = get_llm_config()
    
    # Apply defaults
    model = model or config.default_model
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    max_tokens = max_tokens or config.default_max_tokens
    temperature = temperature or config.default_temperature
    
    # Build system prompt with tools
    enhanced_system_prompt = _build_system_prompt_with_tools(system_prompt, tools)
    
    # Enhance prompt for structured output
    if output_model:
        schema_str = json.dumps(output_model.model_json_schema(), indent=2)
        enhanced_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Respond with valid JSON only. No markdown, no explanations, "
            "just the JSON object.\n"
            f"Follow this exact schema:\n```json\n{schema_str}\n```"
        )
    else:
        enhanced_prompt = prompt
    
    logger.info(
        "llm_call_start",
        model=model,
        prompt_length=len(enhanced_prompt),
        has_tools=bool(tools),
        structured_output=bool(output_model)
    )
    
    # Define retry decorator
    @retry(
        stop=stop_after_attempt(config.retry_attempts),
        wait=wait_exponential(
            multiplier=1,
            min=config.retry_min_wait,
            max=config.retry_max_wait
        ),
        retry=retry_if_exception_type((LLMRateLimitError, LLMTimeoutError, ConnectionError)),
        reraise=True
    )
    async def _make_request() -> str:
        """Inner function with retry logic."""
        client = await get_llm_client()
        
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=enhanced_system_prompt,
                    messages=[{"role": "user", "content": enhanced_prompt}],
                    **kwargs
                ),
                timeout=config.timeout
            )
            
            # Extract text from response
            if hasattr(response, 'content') and isinstance(response.content, list):
                text_blocks = [
                    block.text for block in response.content
                    if hasattr(block, 'text')
                ]
                content = "".join(text_blocks)
            else:
                content = str(response)
            
            # Log usage
            if hasattr(response, 'usage'):
                usage = response.usage
                logger.info(
                    "llm_usage",
                    input_tokens=getattr(usage, 'input_tokens', 0),
                    output_tokens=getattr(usage, 'output_tokens', 0)
                )
            
            return content
            
        except asyncio.TimeoutError as e:
            raise LLMTimeoutError(f"Request timeout after {config.timeout}s")
            
        except Exception as e:
            # Classify and potentially wrap error
            classified = _classify_error(e)
            logger.error(
                "llm_request_failed",
                error=str(e),
                error_type=type(e).__name__,
                classified_type=type(classified).__name__
            )
            raise classified
    
    # Execute with retry
    try:
        content = await _make_request()
        
    except RetryError as e:
        # All retries exhausted
        logger.error("llm_retries_exhausted", attempts=config.retry_attempts)
        raise LLMError(
            f"Failed after {config.retry_attempts} attempts: {e.last_attempt.exception()}"
        )
    
    # Parse structured output if requested
    if output_model:
        try:
            return _parse_structured_output(content, output_model)
        except Exception as e:
            logger.error(
                "structured_output_parsing_failed",
                error=str(e),
                content_preview=content[:200]
            )
            raise LLMParseError(
                f"Failed to parse output as {output_model.__name__}: {str(e)}"
            )
    
    return content

@dataclass
class LLMConfig:
    """Global LLM configuration."""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: str = DEFAULT_MODEL
    default_max_tokens: int = DEFAULT_MAX_TOKENS
    default_temperature: float = DEFAULT_TEMPERATURE
    timeout: int = DEFAULT_TIMEOUT
    retry_attempts: int = 3
    retry_min_wait: float = 1.0
    retry_max_wait: float = 10.0


# Global config instance
_llm_config = LLMConfig()


def configure_llm(config: LLMConfig) -> None:
    """Configure global LLM settings."""
    global _llm_config
    _llm_config = config


def get_llm_config() -> LLMConfig:
    """Get current LLM configuration."""
    return _llm_config


async def call_llm_stream(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    tools: Optional[List[Any]] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    **kwargs
) -> AsyncGenerator[str, None]:
    """
    Stream LLM response with error handling.
    
    Args:
        prompt: User prompt
        model: Model name (uses config default if not provided)
        system_prompt: System prompt (uses config default if not provided)
        tools: Optional list of tools to include in system prompt
        max_tokens: Max tokens to generate
        temperature: Sampling temperature
        **kwargs: Additional API parameters
        
    Yields:
        Token strings
        
    Raises:
        LLMError: On streaming failures
        
    Examples:
        async for token in call_llm_stream("Write a story"):
            print(token, end="", flush=True)
    """
    logger = structlog.get_logger(__name__)
    config = get_llm_config()
    
    # Apply defaults
    model = model or config.default_model
    system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
    max_tokens = max_tokens or config.default_max_tokens
    temperature = temperature or config.default_temperature
    
    # Build system prompt with tools
    enhanced_system_prompt = _build_system_prompt_with_tools(system_prompt, tools)
    
    logger.info(
        "llm_stream_start",
        model=model,
        prompt_length=len(prompt),
        has_tools=bool(tools)
    )
    
    client = await get_llm_client()
    
    try:
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=enhanced_system_prompt,
            messages=[{"role": "user", "content": prompt}],
            **kwargs
        ) as stream:
            async for text in stream.text_stream:
                if text:  # Filter empty strings
                    yield text
        
        # Log final usage
        try:
            final_message = await stream.get_final_message()
            if hasattr(final_message, 'usage'):
                usage = final_message.usage
                logger.info(
                    "llm_stream_complete",
                    input_tokens=getattr(usage, 'input_tokens', 0),
                    output_tokens=getattr(usage, 'output_tokens', 0)
                )
        except Exception:
            pass  # Don't fail on metrics
        
    except asyncio.CancelledError:
        logger.info("llm_stream_cancelled")
        raise
        
    except Exception as e:
        logger.error("llm_stream_failed", error=str(e), error_type=type(e).__name__)
        raise LLMError(f"Streaming failed: {str(e)}")


def _parse_structured_output(content: str, output_model: Type[T]) -> T:
    """
    Parse structured output with multiple fallback strategies.
    
    Args:
        content: Raw LLM output
        output_model: Target Pydantic model
        
    Returns:
        Parsed model instance
        
    Raises:
        Exception: If all parsing strategies fail
    """
    strategies = [
        _parse_direct,
        _parse_strip_markdown,
        _parse_extract_json,
        _parse_repair_json,
    ]
    
    last_error = None
    for strategy in strategies:
        try:
            return strategy(content, output_model)
        except Exception as e:
            last_error = e
            continue
    
    # All strategies failed
    raise last_error or ValueError("All parsing strategies failed")


def _parse_direct(content: str, model: Type[T]) -> T:
    """Parse directly as JSON."""
    data = json.loads(content.strip())
    return model.model_validate(data)


def _parse_strip_markdown(content: str, model: Type[T]) -> T:
    """Strip markdown code fences and parse."""
    cleaned = content.strip()
    
    # Remove ```json and ``` markers
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line if it's a fence
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        # Remove last line if it's a fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    
    data = json.loads(cleaned.strip())
    return model.model_validate(data)


def _parse_extract_json(content: str, model: Type[T]) -> T:
    """Extract JSON object from text."""
    import re
    
    # Look for JSON object
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, content, re.DOTALL)
    
    if not matches:
        raise ValueError("No JSON object found in content")
    
    # Try each match (in case there are multiple)
    for match in matches:
        try:
            data = json.loads(match)
            return model.model_validate(data)
        except Exception:
            continue
    
    raise ValueError("No valid JSON object found")


def _parse_repair_json(content: str, model: Type[T]) -> T:
    """Attempt to repair common JSON issues."""
    import re
    
    # Extract potential JSON
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if not json_match:
        raise ValueError("No JSON-like content found")
    
    json_str = json_match.group(0)
    
    # Common repairs
    repairs = [
        (r"'", '"'),  # Single to double quotes
        (r',\s*}', '}'),  # Trailing commas in objects
        (r',\s*]', ']'),  # Trailing commas in arrays
        (r':\s*None', ': null'),  # Python None to JSON null
        (r':\s*True', ': true'),  # Python True to JSON true
        (r':\s*False', ': false'),  # Python False to JSON false
    ]
    
    for pattern, replacement in repairs:
        json_str = re.sub(pattern, replacement, json_str)
    
    data = json.loads(json_str)
    return model.model_validate(data)
