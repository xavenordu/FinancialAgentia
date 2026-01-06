Dexter — Autonomous Financial Research Agent (TypeScript + Python)

This repository contains Dexter, an AI agent for structured financial research. It combines a TypeScript terminal UI (Ink) with a Python FastAPI backend (a port-in-progress of the original agent logic). The backend uses pydantic and LangChain for LLM integration and exposes a streaming endpoint the UI consumes.

This README explains how to set up the project for development, run the frontend and backend, run the tests, and deploy a basic production-ready configuration.

---

## Project layout (high level)

- `src/` — TypeScript Ink terminal UI and React components. This remains the interactive client.
- `python-backend/` — Python FastAPI backend with the ported agent logic and LLM wrapper.
  - `python-backend/app/main.py` — FastAPI entrypoint; streaming `/query` endpoint using SSE
  - `python-backend/dexter_py/` — Python package containing the agent port (schemas, orchestrator, phases)
  - `python-backend/requirements.txt` — Python dependencies for the backend
  - `python-backend/tests/` — pytest tests for backend endpoints
- `env.example` / `python-backend/.env.example` — example env vars (API keys and backend API key)

---

## Design decisions & goals

- Keep the TypeScript Ink UI to preserve the terminal UX while porting backend logic incrementally to Python.
- Use FastAPI + SSE (Server-Sent Events) for robust streaming from the LLM to the UI.
- Use pydantic models in Python to mirror TypeScript schemas (structured LLM outputs, plans, state).
- Support multiple LLM providers (OpenAI by default; Anthropic / Google optionally) using LangChain when installed.
- Make the backend production-friendly: optional `BACKEND_API_KEY`, logging, readiness endpoint, and tests.

---

## Prerequisites

- Python 3.10+
- Node/Bun environment for the TypeScript frontend (the repo uses `bun` in `package.json` but `node` may also be used if you adapt the scripts).
- API keys:
  - `OPENAI_API_KEY` (required to call OpenAI)
  - `ANTHROPIC_API_KEY` (optional)
  - `GOOGLE_API_KEY` (optional)
  - `BACKEND_API_KEY` (optional; if set the backend requires requests to include `X-API-Key: <value>`)

Install Python dependencies (backend):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r python-backend\requirements.txt
# Also install langchain & SDKs for provider support:
python -m pip install langchain openai
# Optional providers:
python -m pip install anthropic google-generative-ai
```

Install frontend dependencies (if using Bun):

```bash
# from repository root
bun install
```

If you don't want Bun, run the TypeScript build using your preferred Node toolchain (adjust scripts accordingly).

---

## Environment variables

Copy the example env file and fill in your keys:

```powershell
cp env.example .env
cp python-backend/.env.example python-backend/.env
# Edit both .env files and add your keys
```

Important variables:
- `OPENAI_API_KEY` — OpenAI API key
- `ANTHROPIC_API_KEY` — Anthropic API key (optional)
- `GOOGLE_API_KEY` — Google GenAI key (optional)
- `BACKEND_API_KEY` — Optional simple auth for the Python backend; if set, clients must send the header `X-API-Key: <value>`

---

## Running the backend (FastAPI)

Start the Python backend locally (development):

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn python-backend.app.main:app --reload
```

Endpoints:
- `GET /health` — basic health check
- `GET /ready` — readiness check (extend to probe provider connectivity)
- `POST /query` — streaming LLM response using SSE (`text/event-stream`). The request body is JSON: `{ "prompt": "..." }`.
  - If `BACKEND_API_KEY` is set, include header `X-API-Key: <value>` (case-insensitive).

The backend uses `call_llm_stream` in `python-backend/dexter_py/model/llm.py` to stream text from the LLM. If the installed LangChain provider supports streaming, tokens are emitted incrementally. The backend frames each chunk as an SSE `data:` event.

---

## Running the frontend (Ink TUI)

The Ink TUI is in `src/`. By default the frontend posts prompts to `http://localhost:8000/query` and consumes the response stream. To start the frontend using Bun:

```powershell
bun run src/index.tsx
```

If you set `BACKEND_API_KEY`, you must ensure the frontend sends the `X-API-Key` header with the same value. You can either export that header in your shell, or modify the frontend to include it in requests; the code can be updated to automatically include the header from environment variables.

---

## Tests

Backend tests live in `python-backend/tests/` and use pytest + FastAPI TestClient. They mock the LLM stream to verify SSE framing and API key handling.

Run tests:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest python-backend\tests -q
```

---

## Production considerations & recommended improvements

This repo includes several production-ready improvements, but here are recommended next steps to harden a production deployment:

- Use a robust secrets manager for API keys (do not store keys in files). Use environment variables or a secrets store.
- Add a proper authentication/authorization layer (API tokens, OAuth) instead of a single `BACKEND_API_KEY`.
- Use SSE JSON events (e.g., `data: {"token":"...","role":"assistant"}`) to include metadata per token.
- Add rate limiting and request quotas to protect the backend from abuse.
- Add retries and backoff for provider calls and circuit breaker for provider outages.
- Add structured logs (JSON), request IDs, and integrate with observability (Prometheus, OpenTelemetry).
- Add CI tests for the TypeScript frontend (typecheck, lint, unit tests) and Python side (pytest + mypy).
- Containerize the backend and run behind a production-ready ingress with TLS.

---

## Contributing

If you'd like to help finish the Python port or improve functionality:

1. Fork the repo
2. Create a feature branch
3. Keep PRs focused and small
4. Add tests for new behavior

If you're interested in porting particular modules, good first tasks are:
- Finish porting the `Execute` phase and `task_executor` with real tool bindings
- Implement and register finance tools under `python-backend/dexter_py/tools/`
- Add frontend SSE parsing to convert events into tokens with metadata

---

## License

MIT

---

If anything is unclear or you'd like me to update the README with screenshots, architecture diagrams, or deployment examples (Docker Compose / Kubernetes), tell me which format you'd prefer and I'll add it.
# Dexter 🤖

Dexter is an autonomous financial research agent that thinks, plans, and learns as it works. It performs analysis using task planning, self-reflection, and real-time market data. Think Claude Code, but built specifically for financial research.


<img width="979" height="651" alt="Screenshot 2025-10-14 at 6 12 35 PM" src="https://github.com/user-attachments/assets/5a2859d4-53cf-4638-998a-15cef3c98038" />

## Overview

Dexter takes complex financial questions and turns them into clear, step-by-step research plans. It runs those tasks using live market data, checks its own work, and refines the results until it has a confident, data-backed answer.  

**Key Capabilities:**
- **Intelligent Task Planning**: Automatically decomposes complex queries into structured research steps
- **Autonomous Execution**: Selects and executes the right tools to gather financial data
- **Self-Validation**: Checks its own work and iterates until tasks are complete
- **Real-Time Financial Data**: Access to income statements, balance sheets, and cash flow statements
- **Safety Features**: Built-in loop detection and step limits to prevent runaway execution

[![Twitter Follow](https://img.shields.io/twitter/follow/virattt?style=social)](https://twitter.com/virattt)

<img width="996" height="639" alt="Screenshot 2025-11-22 at 1 45 07 PM" src="https://github.com/user-attachments/assets/8915fd70-82c9-4775-bdf9-78d5baf28a8a" />


### Prerequisites

- [Bun](https://bun.com) runtime (v1.0 or higher)
- OpenAI API key (get [here](https://platform.openai.com/api-keys))
- Financial Datasets API key (get [here](https://financialdatasets.ai))
- Tavily API key (get [here](https://tavily.com)) - optional, for web search

#### Installing Bun

If you don't have Bun installed, you can install it using curl:

**macOS/Linux:**
```bash
curl -fsSL https://bun.com/install | bash
```

**Windows:**
```bash
powershell -c "irm bun.sh/install.ps1|iex"
```

After installation, restart your terminal and verify Bun is installed:
```bash
bun --version
```

### Installing Dexter

1. Clone the repository:
```bash
git clone https://github.com/virattt/dexter.git
cd dexter
```

2. Install dependencies with Bun:
```bash
bun install
```

3. Set up your environment variables:
```bash
# Copy the example environment file (from parent directory)
cp env.example .env

# Edit .env and add your API keys
# OPENAI_API_KEY=your-openai-api-key
# FINANCIAL_DATASETS_API_KEY=your-financial-datasets-api-key
# TAVILY_API_KEY=your-tavily-api-key
```

### Usage

Run Dexter in interactive mode:
```bash
bun start
```

Or with watch mode for development:
```bash
bun dev
```

### Example Queries

Try asking Dexter questions like:
- "What was Apple's revenue growth over the last 4 quarters?"
- "Compare Microsoft and Google's operating margins for 2023"
- "Analyze Tesla's cash flow trends over the past year"
- "What is Amazon's debt-to-equity ratio based on recent financials?"

Dexter will automatically:
1. Break down your question into research tasks
2. Fetch the necessary financial data
3. Perform calculations and analysis
4. Provide a comprehensive, data-rich answer

## Architecture

Dexter uses a multi-agent architecture with specialized components:

- **Planning Agent**: Analyzes queries and creates structured task lists
- **Action Agent**: Selects appropriate tools and executes research steps
- **Validation Agent**: Verifies task completion and data sufficiency
- **Answer Agent**: Synthesizes findings into comprehensive responses

## Tech Stack

- **Runtime**: [Bun](https://bun.sh)
- **UI Framework**: [React](https://react.dev) + [Ink](https://github.com/vadimdemedes/ink) (terminal UI)
- **LLM Integration**: [LangChain.js](https://js.langchain.com) with multi-provider support (OpenAI, Anthropic, Google)
- **Schema Validation**: [Zod](https://zod.dev)
- **Language**: TypeScript


### Changing Models

Type `/model` in the CLI to switch between:
- GPT 4.1 (OpenAI)
- Claude Sonnet 4.5 (Anthropic)
- Gemini 3 (Google)

## How to Contribute

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: Please keep your pull requests small and focused.  This will make it easier to review and merge.


## License

This project is licensed under the MIT License.

