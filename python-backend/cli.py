import typer
import asyncio
from dexter_py.model.llm import call_llm

app = typer.Typer()

@app.command()
def ask(prompt: str):
    """Ask the local LLM wrapper a prompt and print the result."""
    result = asyncio.run(call_llm(prompt))
    print("\nResponse:\n")
    print(result)


if __name__ == "__main__":
    app()
