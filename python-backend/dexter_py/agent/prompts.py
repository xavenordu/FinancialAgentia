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
