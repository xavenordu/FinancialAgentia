from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel
from typing import AsyncGenerator
import os
import json
import uuid

# Structured logging
import structlog

# Rate limiting
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded

# Metrics
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from dexter_py.model.llm import call_llm_stream


# Configure structlog for JSON output
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger("dexter_backend")


app = FastAPI(title="Dexter Python Backend")

# Allow local dev frontends to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiter (10 requests per minute per remote address by default)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


# Prometheus metrics
REQUEST_COUNT = Counter("dexter_requests_total", "Total requests received")


class Query(BaseModel):
    prompt: str


@app.on_event("startup")
async def startup():
    logger.info("startup", event="starting dexter python backend")


@app.on_event("shutdown")
async def shutdown():
    logger.info("shutdown", event="shutting down dexter python backend")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    # For now readiness is same as health; extend to check LLM provider connectivity
    return {"ready": True}


@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


def _verify_jwt(token: str) -> dict:
    """Verify a JWT token using JWT_SECRET (HS256) and return the payload.

    If `JWT_SECRET` is not set, this function will raise a RuntimeError.
    """
    from jose import jwt, JWTError

    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET not configured")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(request: Request) -> None:
    """Authentication dependency:
    - If `JWT_SECRET` is set, expect `Authorization: Bearer <token>` and validate JWT.
    - Otherwise, if `BACKEND_API_KEY` is set, accept `X-API-Key: <value>` header.
    - If neither configured, no auth is required (development mode).
    """
    jwt_secret = os.getenv("JWT_SECRET")
    if jwt_secret:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if not auth or not auth.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authorization header missing or invalid")
        token = auth.split(" ", 1)[1]
        payload = _verify_jwt(token)
        # attach payload to request state for handlers
        request.state.user = payload
        return

    expected = os.getenv("BACKEND_API_KEY")
    if not expected:
        # No auth configured
        return
    provided = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.middleware("http")
async def add_request_id_and_count(request: Request, call_next):
    # Add a request id and increment metrics
    rid = str(uuid.uuid4())
    request.state.request_id = rid
    REQUEST_COUNT.inc()
    # Add request_id to structlog context for the duration of the request
    structlog.contextvars.bind_contextvars(request_id=rid)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    response.headers["X-Request-Id"] = rid
    return response


@app.post("/query")
@limiter.limit("10/minute")
async def query(request: Request, q: Query):
    """Stream the LLM response for the given prompt as Server-Sent Events (SSE).

    Each token/chunk is framed as an SSE `data:` event containing a JSON
    object with fields like `token`, `role`, and `request_id`.
    """
    # Enforce authentication if configured
    await require_auth(request)

    request_id = getattr(request.state, "request_id", None)

    async def event_stream() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in call_llm_stream(q.prompt):
                if chunk is None:
                    continue
                payload = {
                    "token": chunk,
                    "role": "assistant",
                    "request_id": request_id,
                }
                s = f"data: {json.dumps(payload)}\n\n"
                yield s.encode("utf-8")
        except Exception as e:
            logger.exception("Error during LLM streaming", error=str(e))
            err_payload = {"error": str(e), "request_id": request_id}
            err = f"event: error\ndata: {json.dumps(err_payload)}\n\n"
            yield err.encode("utf-8")

    return StreamingResponse(event_stream(), media_type="text/event-stream; charset=utf-8")

