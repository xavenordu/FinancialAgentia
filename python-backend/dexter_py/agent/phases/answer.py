"""
Production-ready Answer Phase with:
- Separation of concerns
- Async file analysis
- Token budget management
- Robust error handling
- Input validation
- Comprehensive logging
- Safety controls
"""

import asyncio
from typing import Any, AsyncGenerator, Optional, List, Dict, Protocol
from dataclasses import dataclass
import json
import re
from pathlib import Path
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential


# ============================================================================
# Configuration & Constants
# ============================================================================

@dataclass
class AnswerConfig:
    """Configuration for answer generation."""
    max_context_tokens: int = 8000  # Max tokens for context assembly
    max_file_analysis_size: int = 2000  # Max chars per file analysis
    max_conversation_history_tokens: int = 2000
    max_task_result_size: int = 1000  # Max chars per task result
    streaming_chunk_size: int = 1  # Tokens per chunk
    enable_file_analysis: bool = True
    enable_prompt_injection_protection: bool = True
    truncation_suffix: str = "... [truncated]"


@dataclass
class StreamMetrics:
    """Metrics for streaming operations."""
    tokens_streamed: int = 0
    errors_encountered: int = 0
    chunks_yielded: int = 0
    duration_ms: float = 0


# ============================================================================
# Abstract Interfaces
# ============================================================================

class Tool(Protocol):
    """Protocol for tools with standardized interface."""
    name: str
    description: str
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute tool asynchronously."""
        ...


class FileAnalyzer(Protocol):
    """Protocol for file analysis."""
    
    async def analyze(self, filepath: str, mode: str = "basic") -> Dict[str, Any]:
        """Analyze a file asynchronously."""
        ...


class LLMClient(Protocol):
    """Protocol for LLM client."""
    
    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream LLM response."""
        ...


# ============================================================================
# File Path Extraction
# ============================================================================

class FilePathExtractor:
    """
    Robust file path extraction with validation.
    Handles quoted paths, escaped quotes, spaces, and various OS formats.
    """
    
    # Comprehensive patterns for different path formats
    PATTERNS = [
        # Quoted paths (with escaped quote support)
        re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*\.(?:csv|txt|json|xlsx|pdf))"', re.IGNORECASE),
        re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*\.(?:csv|txt|json|xlsx|pdf))'", re.IGNORECASE),
        
        # Windows absolute paths (C:\path\to\file.csv)
        re.compile(r'\b([A-Za-z]:[/\\][\w\s\-./\\]+\.(?:csv|txt|json|xlsx|pdf))\b', re.IGNORECASE),
        
        # Unix absolute paths (/path/to/file.csv)
        re.compile(r'\b(/[\w\s\-./]+\.(?:csv|txt|json|xlsx|pdf))\b', re.IGNORECASE),
        
        # Relative paths (./path/file.csv or ../path/file.csv)
        re.compile(r'\b(\.{1,2}/[\w\s\-./]+\.(?:csv|txt|json|xlsx|pdf))\b', re.IGNORECASE),
    ]
    
    def __init__(self, logger: Optional[structlog.BoundLogger] = None):
        self.logger = logger or structlog.get_logger(__name__)
    
    def extract_paths(self, text: str) -> List[str]:
        """
        Extract file paths from text with deduplication and validation.
        
        Args:
            text: Text to extract paths from
            
        Returns:
            List of unique, validated file paths in order of appearance
        """
        found_paths: List[str] = []
        seen: set = set()
        
        for pattern in self.PATTERNS:
            for match in pattern.finditer(text):
                path = match.group(1)
                
                # Normalize path
                path = path.strip().replace('\\\\', '\\')
                
                # Skip if already found
                if path in seen:
                    continue
                
                # Basic validation
                if self._is_valid_path(path):
                    found_paths.append(path)
                    seen.add(path)
        
        self.logger.info("paths_extracted", count=len(found_paths), paths=found_paths)
        return found_paths
    
    def _is_valid_path(self, path: str) -> bool:
        """Validate path structure."""
        if not path or len(path) > 500:  # Reject empty or suspiciously long paths
            return False
        
        # Must have valid extension
        valid_extensions = {'.csv', '.txt', '.json', '.xlsx', '.pdf'}
        path_obj = Path(path)
        
        return path_obj.suffix.lower() in valid_extensions


# ============================================================================
# Context Assembly
# ============================================================================

class ContextAssembler:
    """
    Assembles context from plans and results with token budget management.
    """
    
    def __init__(
        self,
        config: AnswerConfig,
        logger: Optional[structlog.BoundLogger] = None
    ):
        self.config = config
        self.logger = logger or structlog.get_logger(__name__)
    
    def assemble(
        self,
        completed_plans: List[Any],
        task_results: Dict[str, Any]
    ) -> str:
        """
        Assemble context with intelligent truncation.
        
        Args:
            completed_plans: List of completed plan objects
            task_results: Dictionary of task results
            
        Returns:
            Assembled context string within token budget
        """
        parts: List[str] = []
        current_size = 0
        
        # Add plans
        if completed_plans:
            parts.append("## Completed Plans\n")
            for i, plan in enumerate(completed_plans, 1):
                plan_str = self._serialize_safely(plan, max_size=500)
                parts.append(f"{i}. {plan_str}\n")
                current_size += len(plan_str)
                
                if current_size > self.config.max_context_tokens * 4:  # ~4 chars per token
                    parts.append(f"... [{len(completed_plans) - i} more plans truncated]\n")
                    break
        
        # Add task results
        if task_results:
            parts.append("\n## Task Results\n")
            for key, value in task_results.items():
                if current_size > self.config.max_context_tokens * 4:
                    remaining = len(task_results) - len(parts) + 2
                    parts.append(f"... [{remaining} more results truncated]\n")
                    break
                
                result_str = self._serialize_safely(
                    value,
                    max_size=self.config.max_task_result_size
                )
                parts.append(f"**{key}:**\n{result_str}\n\n")
                current_size += len(result_str)
        
        context = "".join(parts) if parts else "No context available."
        
        self.logger.info(
            "context_assembled",
            plans_count=len(completed_plans) if completed_plans else 0,
            results_count=len(task_results) if task_results else 0,
            context_size=len(context)
        )
        
        return context
    
    def _serialize_safely(self, obj: Any, max_size: int) -> str:
        """
        Serialize object with size limits and error handling.
        
        Args:
            obj: Object to serialize
            max_size: Maximum size in characters
            
        Returns:
            Serialized string, truncated if necessary
        """
        try:
            if isinstance(obj, str):
                serialized = obj
            elif isinstance(obj, (dict, list)):
                serialized = json.dumps(obj, indent=2, default=str)
            else:
                serialized = str(obj)
            
            # Truncate if too large
            if len(serialized) > max_size:
                serialized = serialized[:max_size] + self.config.truncation_suffix
            
            return serialized
            
        except Exception as e:
            self.logger.warning("serialization_failed", error=str(e))
            return f"[Serialization error: {type(obj).__name__}]"


# ============================================================================
# File Analysis
# ============================================================================

class AsyncFileAnalyzer:
    """
    Async file analyzer with timeout and error handling.
    """
    
    def __init__(
        self,
        file_analyzer: Optional[FileAnalyzer],
        config: AnswerConfig,
        logger: Optional[structlog.BoundLogger] = None
    ):
        self.file_analyzer = file_analyzer
        self.config = config
        self.logger = logger or structlog.get_logger(__name__)
    
    async def analyze_files(self, file_paths: List[str]) -> List[str]:
        """
        Analyze multiple files concurrently with timeout.
        
        Args:
            file_paths: List of file paths to analyze
            
        Returns:
            List of analysis result strings
        """
        if not file_paths or not self.file_analyzer:
            return []
        
        # Analyze files concurrently with timeout
        tasks = [
            self._analyze_single_file(path)
            for path in file_paths
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and format results
        formatted_results = []
        for path, result in zip(file_paths, results):
            if isinstance(result, Exception):
                self.logger.warning("file_analysis_failed", path=path, error=str(result))
                formatted_results.append(f"**{path}:** Analysis failed - {str(result)}")
            elif result:
                formatted_results.append(result)
        
        return formatted_results
    
    async def _analyze_single_file(self, path: str) -> str:
        """
        Analyze a single file with timeout.
        
        Args:
            path: File path to analyze
            
        Returns:
            Formatted analysis string
        """
        try:
            # Add timeout to prevent hanging
            result = await asyncio.wait_for(
                self.file_analyzer.analyze(path, mode="basic"),
                timeout=10.0  # 10 second timeout per file
            )
            
            # Validate result
            if not isinstance(result, dict):
                return f"**{path}:** Invalid analysis result"
            
            if "error" in result:
                return f"**{path}:** {result['error']}"
            
            # Format and truncate
            analysis_str = json.dumps(result, indent=2)
            if len(analysis_str) > self.config.max_file_analysis_size:
                analysis_str = analysis_str[:self.config.max_file_analysis_size] + \
                              self.config.truncation_suffix
            
            return f"**{path}:**\n```json\n{analysis_str}\n```\n"
            
        except asyncio.TimeoutError:
            self.logger.warning("file_analysis_timeout", path=path)
            return f"**{path}:** Analysis timeout"
        except Exception as e:
            self.logger.error("file_analysis_error", path=path, error=str(e))
            raise


# ============================================================================
# Prompt Injection Protection
# ============================================================================

class PromptInjectionProtector:
    """
    Protects against prompt injection attacks.
    """
    
    SUSPICIOUS_PATTERNS = [
        re.compile(r'ignore\s+(previous|above|prior)\s+instructions?', re.IGNORECASE),
        re.compile(r'disregard\s+(previous|above|prior)', re.IGNORECASE),
        re.compile(r'new\s+instructions?:', re.IGNORECASE),
        re.compile(r'system\s+prompt:', re.IGNORECASE),
        re.compile(r'you\s+are\s+now', re.IGNORECASE),
        re.compile(r'forget\s+(everything|all)', re.IGNORECASE),
    ]
    
    def __init__(self, logger: Optional[structlog.BoundLogger] = None):
        self.logger = logger or structlog.get_logger(__name__)
    
    def sanitize(self, user_input: str) -> str:
        """
        Sanitize user input to prevent prompt injection.
        
        Args:
            user_input: Raw user input
            
        Returns:
            Sanitized input
        """
        if not user_input:
            return user_input
        
        # Check for suspicious patterns
        for pattern in self.SUSPICIOUS_PATTERNS:
            if pattern.search(user_input):
                self.logger.warning(
                    "suspicious_pattern_detected",
                    pattern=pattern.pattern
                )
        
        # Escape special markers that might break prompt structure
        sanitized = user_input.replace("```", "'''")
        sanitized = sanitized.replace("<|", "&lt;|")
        sanitized = sanitized.replace("|>", "|&gt;")
        
        return sanitized


# ============================================================================
# System Prompt Builder
# ============================================================================

class SystemPromptBuilder:
    """
    Builds system prompts with tool descriptions.
    """
    
    BASE_PROMPT = (
        "You are FinancialAgentia, an AI assistant specialized in deep financial analysis. "
        "Your role is to interpret research results, evaluate financial data, and synthesize "
        "comprehensive conclusions based on available information."
    )
    
    def __init__(self, logger: Optional[structlog.BoundLogger] = None):
        self.logger = logger or structlog.get_logger(__name__)
    
    def build(self, tools: Optional[List[Tool]] = None) -> str:
        """
        Build system prompt with optional tool descriptions.
        
        Args:
            tools: Optional list of available tools
            
        Returns:
            Complete system prompt
        """
        parts = [self.BASE_PROMPT]
        
        if tools:
            tool_descriptions = []
            for tool in tools:
                desc = self._get_tool_description(tool)
                if desc:
                    tool_descriptions.append(f"- **{tool.name}**: {desc}")
            
            if tool_descriptions:
                parts.append("\n\n## Available Tools\n")
                parts.extend(tool_descriptions)
        
        return "\n".join(parts)
    
    def _get_tool_description(self, tool: Tool) -> str:
        """
        Safely extract tool description.
        
        Args:
            tool: Tool object
            
        Returns:
            Tool description string
        """
        try:
            # Try standard attributes
            if hasattr(tool, 'description') and tool.description:
                return tool.description
            
            # Fallback to name
            if hasattr(tool, 'name'):
                return f"Tool: {tool.name}"
            
            # Last resort
            return "No description available"
            
        except Exception as e:
            self.logger.warning("tool_description_error", error=str(e))
            return "Tool description unavailable"


# ============================================================================
# Streaming Response Handler
# ============================================================================

class StreamingResponseHandler:
    """
    Handles LLM streaming with error recovery and metrics.
    """
    
    def __init__(
        self,
        llm_client: LLMClient,
        logger: Optional[structlog.BoundLogger] = None
    ):
        self.llm_client = llm_client
        self.logger = logger or structlog.get_logger(__name__)
    
    async def stream_with_recovery(
        self,
        prompt: str,
        system_prompt: str,
        model: str,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Stream LLM response with error handling and metrics.
        
        Args:
            prompt: User prompt
            system_prompt: System prompt
            model: Model name
            **kwargs: Additional LLM parameters
            
        Yields:
            Token strings
        """
        metrics = StreamMetrics()
        start_time = asyncio.get_event_loop().time()
        
        try:
            async for token in self.llm_client.stream(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                **kwargs
            ):
                # Validate token
                if not isinstance(token, str):
                    self.logger.warning("invalid_token_type", token_type=type(token))
                    continue
                
                # Filter and sanitize
                sanitized_token = self._sanitize_token(token)
                if sanitized_token:
                    metrics.tokens_streamed += len(sanitized_token)
                    metrics.chunks_yielded += 1
                    yield sanitized_token
            
            # Record success metrics
            metrics.duration_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            self.logger.info("streaming_complete", metrics=metrics.__dict__)
            
        except asyncio.CancelledError:
            self.logger.info("streaming_cancelled")
            raise
            
        except Exception as e:
            metrics.errors_encountered += 1
            self.logger.error("streaming_error", error=str(e), metrics=metrics.__dict__)
            
            # Yield error message to user
            yield f"\n\n[Error: Response generation failed - {str(e)}]"
    
    def _sanitize_token(self, token: str) -> str:
        """
        Sanitize individual tokens.
        
        Args:
            token: Raw token string
            
        Returns:
            Sanitized token
        """
        # Remove control characters
        sanitized = ''.join(char for char in token if ord(char) >= 32 or char in '\n\t')
        return sanitized


# ============================================================================
# Input Validator
# ============================================================================

class InputValidator:
    """
    Validates inputs to the answer phase.
    """
    
    def __init__(self, logger: Optional[structlog.BoundLogger] = None):
        self.logger = logger or structlog.get_logger(__name__)
    
    def validate_run_inputs(
        self,
        query: str,
        completed_plans: Any,
        task_results: Any,
        message_history: Any
    ) -> None:
        """
        Validate all inputs to the run method.
        
        Args:
            query: User query
            completed_plans: Completed plans
            task_results: Task results
            message_history: Message history
            
        Raises:
            ValueError: If validation fails
        """
        # Validate query
        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")
        
        if len(query) > 10000:
            raise ValueError("query exceeds maximum length (10000 chars)")
        
        # Validate completed_plans
        if completed_plans is not None and not isinstance(completed_plans, (list, tuple)):
            raise ValueError("completed_plans must be a list or tuple")
        
        # Validate task_results
        if task_results is not None and not isinstance(task_results, dict):
            raise ValueError("task_results must be a dictionary")
        
        # Validate message_history interface
        if message_history is not None:
            required_methods = ['has_messages', 'format_for_planning']
            for method in required_methods:
                if not hasattr(message_history, method):
                    raise ValueError(
                        f"message_history must implement {method}() method"
                    )
        
        self.logger.debug("inputs_validated")


# ============================================================================
# Main Answer Phase
# ============================================================================

class AnswerPhase:
    """
    Production-ready answer phase with comprehensive error handling,
    async file analysis, token budget management, and safety controls.
    """
    
    def __init__(
        self,
        model: str,
        context_manager: Any,
        llm_client: LLMClient,
        file_analyzer: Optional[FileAnalyzer] = None,
        tools: Optional[List[Tool]] = None,
        config: Optional[AnswerConfig] = None
    ):
        """
        Initialize answer phase with dependencies.
        
        Args:
            model: Model name
            context_manager: Context manager instance
            llm_client: LLM client for streaming
            file_analyzer: Optional file analyzer
            tools: Optional list of tools
            config: Optional configuration
        """
        self.model = model
        self.context_manager = context_manager
        self.llm_client = llm_client
        self.tools = tools or []
        self.config = config or AnswerConfig()
        
        # Initialize components
        self.logger = structlog.get_logger(__name__)
        self.path_extractor = FilePathExtractor(self.logger)
        self.context_assembler = ContextAssembler(self.config, self.logger)
        self.file_analyzer = AsyncFileAnalyzer(file_analyzer, self.config, self.logger)
        self.injection_protector = PromptInjectionProtector(self.logger)
        self.prompt_builder = SystemPromptBuilder(self.logger)
        self.stream_handler = StreamingResponseHandler(llm_client, self.logger)
        self.validator = InputValidator(self.logger)
    
    async def run(
        self,
        *,
        query: str,
        completed_plans: List[Any],
        task_results: Dict[str, Any],
        message_history: Any = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate streaming answer with full safety and error handling.
        
        Args:
            query: User query
            completed_plans: List of completed plans
            task_results: Dictionary of task results
            message_history: Optional message history for context
            
        Yields:
            Token strings from LLM response
        """
        # Validate inputs
        self.validator.validate_run_inputs(
            query, completed_plans, task_results, message_history
        )
        
        self.logger.info(
            "answer_phase_start",
            query_length=len(query),
            plans_count=len(completed_plans) if completed_plans else 0,
            results_count=len(task_results) if task_results else 0
        )
        
        try:
            # 1. Sanitize query
            if self.config.enable_prompt_injection_protection:
                sanitized_query = self.injection_protector.sanitize(query)
            else:
                sanitized_query = query
            
            # 2. Build context from plans and results
            research_context = self.context_assembler.assemble(
                completed_plans or [],
                task_results or {}
            )
            
            # 3. Add conversation history if available
            conversation_context = ""
            if message_history and message_history.has_messages():
                conversation_context = message_history.format_for_planning()
                
                # Truncate if too large
                max_size = self.config.max_conversation_history_tokens * 4
                if len(conversation_context) > max_size:
                    conversation_context = conversation_context[:max_size] + \
                                          self.config.truncation_suffix
            
            # 4. Analyze files if enabled
            file_analyses_text = ""
            if self.config.enable_file_analysis:
                file_paths = self.path_extractor.extract_paths(sanitized_query)
                if file_paths:
                    file_analyses = await self.file_analyzer.analyze_files(file_paths)
                    if file_analyses:
                        file_analyses_text = "\n\n## File Analyses\n" + "\n".join(file_analyses)
            
            # 5. Build final prompt
            prompt = self._build_final_prompt(
                sanitized_query,
                research_context,
                conversation_context,
                file_analyses_text
            )
            
            # 6. Build system prompt
            system_prompt = self.prompt_builder.build(self.tools)
            
            # 7. Stream response with error handling
            async for token in self.stream_handler.stream_with_recovery(
                prompt=prompt,
                system_prompt=system_prompt,
                model=self.model
            ):
                yield token
            
            self.logger.info("answer_phase_complete")
            
        except Exception as e:
            self.logger.error("answer_phase_failed", error=str(e), query_length=len(query))
            yield f"\n\n[Error: Failed to generate answer - {str(e)}]"
    
    def _build_final_prompt(
        self,
        query: str,
        research_context: str,
        conversation_context: str,
        file_analyses: str
    ) -> str:
        """
        Build final prompt with all components.
        
        Args:
            query: Sanitized user query
            research_context: Context from research
            conversation_context: Conversation history
            file_analyses: File analysis results
            
        Returns:
            Complete prompt string
        """
        parts = []
        
        # Add conversation history first (earliest context)
        if conversation_context:
            parts.append(conversation_context)
            parts.append("\n---\n")
        
        # Add research context
        if research_context:
            parts.append("## Research Context\n")
            parts.append(research_context)
            parts.append("\n")
        
        # Add file analyses
        if file_analyses:
            parts.append(file_analyses)
            parts.append("\n")
        
        # Add current query
        parts.append("## Current Query\n")
        parts.append(query)
        parts.append("\n\n")
        parts.append("Please provide a comprehensive answer based on the research and context above.")
        
        return "".join(parts)