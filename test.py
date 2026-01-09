"""
Standalone test for OpenAI.
This script tests calling OpenAI's Chat Completions API via LangChain and prints the response.
"""

import os
import asyncio

# Make sure you have the LangChain OpenAI integration installed:
# pip install langchain-openai langchain

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    raise RuntimeError("Please install langchain-openai first: pip install langchain-openai")

# Load environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # Optional override for custom endpoints

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set in environment. Set it before running this script.")


async def main():
    # Create the LangChain ChatOpenAI instance
    chat = ChatOpenAI(
        model="gpt-4.1",  # Adjust to the model you want to test
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,  # None by default, override only if needed
        streaming=False,  # set True if you want streaming responses
    )

    # The prompt to test
    messages = [{"role": "user", "content": "Hello OpenAI!"}]

    # Call the model (run synchronous call in a thread to keep async structure)
    response = await asyncio.to_thread(lambda: chat.invoke(messages))

    print("Response from OpenAI:")
    print(response)


if __name__ == "__main__":
    asyncio.run(main())
