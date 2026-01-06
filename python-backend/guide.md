Dexter Python backend — guide

This guide explains how to run the Python backend with streaming enabled and how the Ink frontend (TypeScript) connects to it.

Overview
- The Python backend exposes a streaming `/query` endpoint at http://localhost:8000/query which returns chunked text from the LLM.
- The Ink React TUI (the original JS frontend) has been updated to POST prompts to this endpoint and consume the response body as a stream, allowing incremental UI updates.

Requirements
- Python 3.10+
- A working OpenAI/Anthropic/Google API key if you plan to actually call an LLM.
  - OPENAI_API_KEY for OpenAI models
  - ANTHROPIC_API_KEY for Anthropic (optional)
  - GOOGLE_API_KEY for Google GenAI (optional)
 - langchain and provider SDKs are required for LLM calls and streaming. Install:

```powershell
python -m pip install langchain openai
# Optional providers (if you plan to use them):
python -m pip install anthropic google-generative-ai
```

If you don't install `langchain`, the Python code will raise errors when attempting to import or call the LLM. The repo includes guards but a proper langchain install is required for runtime.

Files of interest
- `python-backend/app/main.py` — FastAPI app; `/query` streams LLM output.
- `python-backend/dexter_py/model/llm.py` — LLM wrapper that supports structured output and streaming.
- `src/hooks/useAgentExecution.ts` — Frontend hook updated to POST to `/query` and consume the response stream.

Quick start (Windows PowerShell)
1. Create and activate a virtual environment, then install requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r python-backend\requirements.txt
```

2. Set your API key(s) in the environment (PowerShell example):

```powershell
$env:OPENAI_API_KEY = "sk-..."
# Optional:
#$env:ANTHROPIC_API_KEY = "..."
#$env:GOOGLE_API_KEY = "..."
```

3. Start the FastAPI server (reload enabled for development):

```powershell
python -m uvicorn python-backend.app.main:app --reload
```

4. Run the original Ink TUI (requires Bun or Node-like environment used in the repo):

```powershell
# From repo root (the TypeScript frontend)
bun run src/index.tsx
# or, if you use node: node --loader ts-node/esm src/index.tsx (project specific)
```

Usage
- Type a query in the TUI. The frontend posts the prompt to `http://localhost:8000/query` and will display the answer as it streams back.
- The backend uses `call_llm_stream` from `dexter_py.model.llm` which attempts to stream tokens when the underlying chat model supports it. If streaming isn't supported by the model or langchain installation, the backend will still return the full response as a single chunk.

Troubleshooting
- If you see `RuntimeError: OPENAI_API_KEY not set in environment`, set the `OPENAI_API_KEY` env var as shown above.
- If streaming does not appear incremental in the UI, check that your FastAPI process is running and that the frontend is connecting to `http://localhost:8000/query` (no proxy). Also ensure the backend's `call_llm_stream` is using a model that supports streaming and your langchain version supports streaming for that provider.

API key (optional)
- If you set `BACKEND_API_KEY` in your environment, the backend will require requests include the header `X-API-Key: <value>` (case-insensitive). This helps restrict access to the backend in development or lightweight deployments.

Running tests
- The repository includes basic pytest tests for the backend. From PowerShell run:

```powershell
# From repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r python-backend\requirements.txt
python -m pytest python-backend\tests -q
```

The tests mock the LLM stream and verify the SSE framing and API key behavior.

Next steps
- Improve chunk framing (e.g., SSE/event formatting) if you need token/meta events.
- Add authentication between frontend and backend for production use.
- Replace the LLM call with a mocked test double for unit/integration tests to avoid API usage.

