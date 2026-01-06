Dexter (Python/TS hybrid) — Functional Overview

This repository contains a TypeScript Ink TUI frontend and a Python FastAPI backend (a port-in-progress of the original TypeScript agent). The goal is to provide an autonomous financial research agent that uses LLMs and a set of tools to answer user queries.

High-level components

1. Frontend (TypeScript / Ink)
   - Location: `src/`
   - Purpose: Terminal UI for interacting with the agent. Uses `ink` to render a TUI that accepts user queries, displays phase progress, task lists, and streaming answers.
   - Key modules:
     - `src/cli.tsx`, `src/index.tsx` — entrypoints and main UI components
     - `src/hooks/useAgentExecution.ts` — orchestrates frontend state and, in this port, sends queries to the Python backend `/query` endpoint.
     - `src/components/*` — UI building blocks (AnswerBox, TaskListView, AgentProgressView, etc.)

2. Backend (Python)
   - Location: `python-backend/`
   - Purpose: Hosts a FastAPI app that handles LLM calls and agent logic. The backend is being ported from the TypeScript agent to Python (pydantic, FastAPI, langchain).
   - Key modules:
     - `python-backend/app/main.py` — FastAPI app exposing `/health` and a streaming `/query` endpoint.
     - `python-backend/dexter_py/model/llm.py` — LLM wrapper (langchain) with structured output and streaming support. Supports OpenAI, optionally Anthropic and Google if available.
     - `python-backend/dexter_py/agent/` — Python port of the agent modules (orchestrator, phases, schema/state models). The port is incremental; many modules are initial stubs that mirror TypeScript signatures.

3. Tools & Utilities
   - Tools are registered in `dexter_py/tools/__init__.py` (currently empty); tool implementations (finance API wrappers, search, etc.) from the original TS project can be ported as needed.
   - `python-backend/dexter_py/utils` contains small helper classes like `ToolContextManager` and `MessageHistory` used by the agent.

Runtime flow

- The TUI sends a POST to `http://localhost:8000/query` with JSON `{ "prompt": "..." }`.
- FastAPI `/query` calls `call_llm_stream` in `dexter_py.model.llm`, which in turn uses langchain chat models to stream tokens.
- The FastAPI endpoint yields token chunks as a `StreamingResponse` with MIME `text/plain`; the TUI consumes the body stream and displays text incrementally.
- The orchestrator (`dexter_py.agent.orchestrator.Agent`) wires phases (Understand, Plan, Execute, Reflect, Answer). Phases currently call into the LLM wrapper for structured outputs (pydantic models) and are progressively being ported.

Current status & limitations

- The Python backend scaffold is functional for basic LLM calls but depends on `langchain` and provider SDKs to actually perform streaming and structured calls.
- Many agent components are placeholders/stubs (tool executors, task executor) to allow incremental porting and testing. They mirror TS call signatures but need full implementations for production behavior.
- Frontend remains the original TypeScript Ink TUI to avoid a full UI rewrite; it now delegates LLM work to the new Python backend.

Next work items

- Complete port of agent modules: `state`, `schemas`, `phases/*`, `task-executor`, and tool implementations.
- Add unit and integration tests with mocked LLMs and streaming to validate frontend-backend flow without real API calls.
- Implement an authentication layer and rate limiting for production use.

Contact points in code

- FastAPI entrypoint: `python-backend/app/main.py`
- LLM wrapper: `python-backend/dexter_py/model/llm.py`
- Agent orchestrator: `python-backend/dexter_py/agent/orchestrator.py`
- Frontend hook (sends queries): `src/hooks/useAgentExecution.ts`

