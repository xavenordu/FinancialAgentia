# Quick Reference: Session Management

## What Was Implemented

### ✅ 1. Session-Based Orchestrator
Agent.run() now accepts session context:
```python
await agent.run(query, session_id=id, session_store=store)
```

### ✅ 2. Session Store (InMemory + Redis)
Thread-safe session persistence:
```python
store = get_session_store()  # Auto-selects based on REDIS_URL
history = store.get(session_id)
store.set(session_id, history)
```

### ✅ 3. FastAPI Endpoints
Four new endpoints for session management:
- `POST /agent/session` - Create session
- `POST /agent/query` - Query with context
- `GET /agent/history` - View history
- `DELETE /agent/history` - Clear history

### ✅ 4. LLM Summarization
Optional smart summaries for each turn:
```bash
export DEXTER_SUMMARIZE_LLM=true  # Enable LLM summaries
```

### ✅ 5. Smart Message Selection
Optional semantic filtering to reduce tokens:
```bash
export DEXTER_USE_EMBEDDINGS=true          # Use embeddings
export DEXTER_MAX_CONTEXT_MESSAGES=10      # Include top-10 similar
```

---

## Files Changed

| File | Change |
|------|--------|
| `orchestrator.py` | Added session_id + session_store params |
| `message_history.py` | Added LLM summarization + embedding selection |
| `app/main.py` | Added 4 session endpoints + startup init |
| `session_store.py` | NEW - InMemory + Redis implementations |

---

## Usage: Client JavaScript

```javascript
// Create or load session
const sessionId = localStorage.getItem("sessionId") || 
                  (await fetch("/agent/session", {method: "POST"}).then(r => r.json())).session_id;
localStorage.setItem("sessionId", sessionId);

// Query with context persistence
async function askAgent(question) {
    const response = await fetch("/agent/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: question, session_id: sessionId }),
        credentials: "include"  // Preserve cookies
    });
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    
    while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        
        const event = JSON.parse(
            decoder.decode(value).replace(/^data: /, "").trim()
        );
        console.log(event.content);  // Stream response
    }
}

// View full conversation
async function showHistory() {
    const hist = await fetch(`/agent/history?session_id=${sessionId}`).then(r => r.json());
    console.log(`${hist.turns} turns in conversation`);
    hist.messages.forEach(msg => {
        console.log(`Q: ${msg.query}\nA: ${msg.answer}\nSummary: ${msg.summary}`);
    });
}

// Clear session
async function clearSession() {
    await fetch(`/agent/history?session_id=${sessionId}`, {method: "DELETE"});
    localStorage.removeItem("sessionId");
}
```

---

## Usage: Python Backend

```python
from dexter_py.utils.session_store import get_session_store
from dexter_py.agent.orchestrator import Orchestrator
import uuid

# Setup
store = get_session_store()  # Auto InMemory or Redis
agent = Orchestrator(model="gpt-4")
session_id = str(uuid.uuid4())

# Multi-turn conversation
queries = [
    "What is Bitcoin?",
    "Why is it valuable?",
    "How do miners earn rewards?"
]

for query in queries:
    # Each query automatically has full context from prior turns
    answer = await agent.run(
        query=query,
        session_id=session_id,
        session_store=store
    )
    print(f"Q: {query}\nA: {answer}\n")

# Access history
history = store.get(session_id)
print(f"Total turns: {len(history)}")
for msg in history.get_all():
    print(f"Turn {msg.id}: {msg.summary}")
```

---

## Environment Configuration

```bash
# .env file

# Session Storage
REDIS_URL=redis://localhost:6379/0          # Or omit for in-memory

# Summarization
DEXTER_SUMMARIZE_LLM=true                   # Use LLM for summaries

# Message Selection
DEXTER_USE_EMBEDDINGS=true                  # Use embedding similarity
DEXTER_MAX_CONTEXT_MESSAGES=10              # Limit context size

# FastAPI Security
JWT_SECRET=your-secret-key                  # JWT auth
BACKEND_API_KEY=your-api-key               # API key auth
SECURE_COOKIES=true                         # Https-only cookies
```

---

## Performance Tips

### Reduce Token Usage
```bash
# Enable smart message selection
DEXTER_USE_EMBEDDINGS=true
DEXTER_MAX_CONTEXT_MESSAGES=5  # Tighter limit

# Enable semantic summaries
DEXTER_SUMMARIZE_LLM=true
```

### Scale to Multiple Instances
```bash
# Use Redis instead of in-memory
REDIS_URL=redis://redis-host:6379/0
```

### Local Development
```bash
# Fastest: no external deps
unset DEXTER_SUMMARIZE_LLM
unset DEXTER_USE_EMBEDDINGS
unset REDIS_URL
```

---

## Testing Checklist

- [ ] Start FastAPI: `uvicorn app.main:app --reload`
- [ ] Create session: `curl -X POST http://localhost:8000/agent/session`
- [ ] Query: `curl -X POST http://localhost:8000/agent/query -d '{"query":"..."}'`
- [ ] View history: `curl http://localhost:8000/agent/history?session_id=...`
- [ ] Clear history: `curl -X DELETE http://localhost:8000/agent/history?session_id=...`
- [ ] Multi-turn: Send 2+ queries with same session_id, verify context
- [ ] Context verification: Check /agent/history shows all turns with context

---

## Troubleshooting

### RedisSessionStore Connection Failed
```
Error: Connection refused
Solution: Ensure Redis running (redis-server) or remove REDIS_URL env var
```

### LLM Summarization Timeout
```
Error: LLM call timeout
Solution: Falls back automatically. If too slow, set DEXTER_SUMMARIZE_LLM=false
```

### Session Data Not Persisting
```
Error: History empty after restart
Solution: Normal if using InMemory. Use REDIS_URL for persistence
```

### Embedding Model Download
```
Error: Downloading sentence-transformers model (~100MB)
Solution: First run will cache. Set DEXTER_USE_EMBEDDINGS=false if unwanted
```

---

## Key Classes & Methods

### Session Store
```python
store.get(session_id: str) → MessageHistory
store.set(session_id: str, history: MessageHistory) → None
store.delete(session_id: str) → None
store.exists(session_id: str) → bool
```

### Message History
```python
history.add_agent_message(query: str, answer: str, summary: str = "") → None
history.get_all() → List[Message]
history.get_by_id(message_id: int) → Message | None
history.last() → Message | None
await history.select_relevant_messages(current_query: str) → List[Message]
history.format_for_planning() → str
history.clear() → None
```

### Agent/Orchestrator
```python
await agent.run(
    query: str,
    message_history: MessageHistory = None,
    session_id: str = None,
    session_store: dict = None,
) → str
```

---

## Endpoints Summary

| Method | Path | Purpose |
|--------|------|---------|
| POST | /agent/session | Create new session |
| POST | /agent/query | Query with context (SSE) |
| GET | /agent/history | Get conversation history |
| DELETE | /agent/history | Clear session history |

**Note:** All endpoints set `session_id` cookie for convenience.

---

## Next Phase: Production Hardening

- [ ] Session TTL and cleanup
- [ ] Session analytics (turn count, response times)
- [ ] Conversation summarization for very long histories
- [ ] Database persistence (PostgreSQL/SQLite)
- [ ] Rate limiting per session
- [ ] Session encryption at rest
- [ ] Audit logging per session
