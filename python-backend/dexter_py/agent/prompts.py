from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


def get_current_date() -> str:
    """
    Returns the current date as a human-readable string in UTC.
    Format: Weekday, Month Day, Year (e.g., Tuesday, January 6, 2026)
    """
    now = datetime.now(timezone.utc)
    return now.strftime('%A, %B %d, %Y')


DEFAULT_SYSTEM_PROMPT = (
    "You are FinancialAgentia, an autonomous financial research agent.\n"
    "Your primary objective is to conduct deep and thorough research on stocks and companies to answer user queries.\n"
    "You are equipped with a set of powerful tools to gather and analyze financial data.\n"
    "You should be methodical, breaking down complex questions into manageable steps and using your tools strategically.\n"
    "Always aim to provide accurate, comprehensive, and well-structured information."
)


UNDERSTAND_SYSTEM_PROMPT_TEMPLATE = (
    "You are the understanding component for Dexter, a financial research agent.\n\n"
    "Your job is to analyze the user's query and extract:\n"
    "1. The user's intent — what they want to accomplish\n"
    "2. Key entities — tickers, companies, dates, metrics, time periods\n\n"
    "Current date: {current_date}\n\n"
    "Guidelines:\n"
    "- Be precise about what the user is asking for\n"
    "- Identify ALL relevant entities (companies, tickers, dates, metrics)\n"
    "- Normalize company names to ticker symbols when possible (e.g., \"Apple\" → \"AAPL\")\n"
    "- Identify time periods (e.g., last quarter, 2024, past 5 years)\n"
    "- Identify specific metrics mentioned (e.g., P/E ratio, revenue, profit margin)\n\n"
    "Return a JSON object with:\n"
    "  intent: A clear statement of what the user wants\n"
    "  entities: Array of extracted entities with type and value\n"
)


def get_understand_system_prompt(date_override: Optional[str] = None) -> str:
    """
    Builds the understanding system prompt with a safe date substitution.
    Allows an optional date override for testing or reproducibility.
    """
    date_value = date_override or get_current_date()
    return UNDERSTAND_SYSTEM_PROMPT_TEMPLATE.format(current_date=date_value)


def build_understand_user_prompt(
    query: str,
    conversation_context: Optional[str] = None
) -> str:
    """
    Builds the user prompt for the understanding module.
    Includes previous conversation context when provided.
    """
    if not query or not isinstance(query, str):
        raise ValueError("Query must be a non-empty string.")

    sections = []

    if conversation_context:
        sections.append(
            "Previous conversation (for context):\n"
            f"{conversation_context.strip()}\n\n---\n"
        )

    sections.append(f"User query: \"{query.strip()}\"\n")
    sections.append("Extract the intent and entities from this query.")

    return "\n".join(sections)


PLAN_SYSTEM_PROMPT_TEMPLATE = (
    "You are the planning component for Dexter, a financial research agent.\n\n"
    "Your job is to create a structured plan for answering the user's query.\n"
    "Break down the query into specific, actionable research tasks.\n\n"
    "Current date: {current_date}\n\n"
    "Guidelines:\n"
    "- Create specific, actionable tasks that can be executed\n"
    "- Identify data sources and tools needed (APIs, databases, etc.)\n"
    "- Order tasks logically (dependencies matter)\n"
    "- Include validation/verification steps\n"
    "- Make tasks specific to financial research (tickers, metrics, periods)\n\n"
    "Return a JSON object with:\n"
    "  summary: Brief overview of the research plan\n"
    "  tasks: Array of tasks with id, description, taskType, toolCalls, dependsOn\n"
)


def get_plan_system_prompt(date_override: Optional[str] = None) -> str:
    """
    Builds the planning system prompt with a safe date substitution.
    Allows an optional date override for testing or reproducibility.
    """
    date_value = date_override or get_current_date()
    return PLAN_SYSTEM_PROMPT_TEMPLATE.format(current_date=date_value)


def build_plan_user_prompt(
    query: str,
    intent: str,
    entities: str,
    prior_work_summary: Optional[str] = None,
    guidance_from_reflection: Optional[str] = None,
    conversation_context: Optional[str] = None
) -> str:
    """
    Builds the user prompt for the planning module.
    Includes conversation context, prior work, and reflection guidance.
    """
    sections = []

    if conversation_context:
        sections.append(
            "Previous conversation context:\n"
            f"{conversation_context.strip()}\n\n"
        )

    sections.append(f"User Query: {query}\n")
    sections.append(f"Intent: {intent}\n")
    sections.append(f"Key Entities: {entities}\n")

    if prior_work_summary:
        sections.append(f"\nPrior Research Attempts:\n{prior_work_summary}\n")

    if guidance_from_reflection:
        sections.append(f"\nGuidance from Previous Iteration:\n{guidance_from_reflection}\n")

    sections.append(
        "\nCreate a detailed research plan that will help answer this query. "
        "Include specific tools/APIs to use and the order of execution."
    )

    return "\n".join(sections)

