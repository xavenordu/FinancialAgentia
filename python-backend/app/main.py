from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import AsyncGenerator
import os
import logging

from dexter_py.model.llm import call_llm_stream


app = FastAPI(title="Dexter Python Backend")

# Allow local dev frontends to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dexter_backend")


class Query(BaseModel):
    prompt: str


@app.on_event("startup")
async def startup():
    logger.info("Starting Dexter Python backend")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down Dexter Python backend")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    # For now readiness is same as health; extend to check LLM provider connectivity
    return {"ready": True}


def _require_api_key(request: Request) -> None:
    expected = os.getenv("BACKEND_API_KEY")
    if not expected:
        return
    provided = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/query")
async def query(request: Request, q: Query):
    """Stream the LLM response for the given prompt as Server-Sent Events (SSE).

    Each token/chunk is framed as an SSE `data:` event; clients can parse SSE or
    treat the body as a plain stream of text chunks.
    """
    # Optional API key enforcement
    _require_api_key(request)

    async def event_stream() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in call_llm_stream(q.prompt):
                if chunk is None:
                    continue
                # Frame as SSE event (data: <chunk>\n\n)
                s = f"data: {chunk}\n\n"
                yield s.encode("utf-8")
        except Exception as e:
            logger.exception("Error during LLM streaming")
            # Send an error event then close
            err = f"event: error\ndata: {str(e)}\n\n"
            yield err.encode("utf-8")

    return StreamingResponse(event_stream(), media_type="text/event-stream; charset=utf-8")
