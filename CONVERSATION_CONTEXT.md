# Persistent Conversation Context Guide

This guide explains how to use FinancialAgentia's persistent conversation context across multiple queries for multi-turn interactions.

## Overview

The agent now maintains conversation history automatically, allowing it to:
- Reference previous queries in subsequent questions
- Understand implicit references (e.g., "What about revenue?" after discussing Apple)
- Build context from multi-turn conversations
- Provide more accurate and relevant responses

## Three Approaches to Context Management

### Approach 1: Automatic Agent History (Recommended for Interactive Use)

The Agent automatically maintains message history. Each query-answer pair is saved for future context.

#### TypeScript Implementation

```typescript
import { Agent } from './agent/orchestrator.js';
import { MessageHistory } from './utils/message-history.js';

// Initialize agent once per conversation session
const agent = new Agent({
  model: 'gpt-4',
  maxIterations: 5,
});

// First query
const answer1 = await agent.run('What is Apple\'s P/E ratio?');
console.log('Answer 1:', answer1);

// Second query - automatically includes context from first
const answer2 = await agent.run('What about their revenue growth?');
console.log('Answer 2:', answer2);

// Access the conversation history if needed
const history = agent.getMessageHistory();
console.log('Total turns:', history.get_all().length);
```

#### Python Implementation

```python
from dexter_py.agent.orchestrator import Agent, AgentOptions
from dexter_py.utils.message_history import MessageHistory

# Initialize agent with persistent history
agent = Agent(AgentOptions(model='gpt-4'))

# First query
answer1 = await agent.run('What is Apple\'s P/E ratio?')
print(f'Answer 1: {answer1}')

# Second query - automatically includes context from first
answer2 = await agent.run('What about their revenue growth?')
print(f'Answer 2: {answer2}')

# Access the conversation history
history = agent.message_history
print(f'Total turns: {len(history)}')
```

**Benefits:**
- Simplest to use
- Context maintained within agent lifecycle
- Perfect for CLI and interactive applications

**Limitations:**
- History is lost when agent is recreated
- Suitable for single-session conversations

---

### Approach 2: Explicit History Management (For Multi-Session Use)

Create and manage MessageHistory explicitly for scenarios where you need to persist context across agent instances.

#### TypeScript Implementation

```typescript
import { Agent } from './agent/orchestrator.js';
import { MessageHistory } from './utils/message-history.js';

// Initialize history once
const history = new MessageHistory('gpt-4');

// Create first agent instance with history
const agent1 = new Agent({ model: 'gpt-4' });
const answer1 = await agent1.run('What is Apple\'s P/E ratio?', history);
console.log('Answer 1:', answer1);

// ... later, create new agent instance with same history
const agent2 = new Agent({ model: 'gpt-4' });
const answer2 = await agent2.run('What about Microsoft?', history);
console.log('Answer 2:', answer2);

// History persists across agent instances
console.log('Conversation turns:', history.getAll().length);
console.log('Last message:', history.last());
```

#### Python Implementation

```python
from dexter_py.agent.orchestrator import Agent, AgentOptions
from dexter_py.utils.message_history import MessageHistory

# Initialize history once (can be persisted to disk)
history = MessageHistory(model='gpt-4')

# Use first agent instance with history
agent1 = Agent(AgentOptions(model='gpt-4'))
answer1 = await agent1.run('What is Apple\'s P/E ratio?', history)
print(f'Answer 1: {answer1}')

# Later, create new agent with same history
agent2 = Agent(AgentOptions(model='gpt-4'))
answer2 = await agent2.run('What about Microsoft?', history)
print(f'Answer 2: {answer2}')

# History persists across agent instances
print(f'Turns: {len(history)}')
print(f'Last message: {history.last()}')
```

**Benefits:**
- Context persists across agent instances
- Allows agent recreation or swapping models
- History can be saved/loaded from storage

**Use Cases:**
- API servers handling multiple client sessions
- Chat applications with persistent conversation state
- Multi-turn dialogue systems

---

### Approach 3: Manual Context Inclusion in Prompts

For maximum control, manually construct prompts that include conversation context.

#### TypeScript Implementation

```typescript
import { Agent } from './agent/orchestrator.js';
import { MessageHistory } from './utils/message-history.js';

const history = new MessageHistory('gpt-4');
const agent = new Agent({ model: 'gpt-4' });

// First query
const answer1 = await agent.run('Analyze Apple\'s financials.', history);

// Manually build context for next query
const conversationContext = history.formatForPlanning();
const enrichedQuery = `${conversationContext}\n\nNow compare with Microsoft.`;

const answer2 = await agent.run(enrichedQuery, history);
```

#### Python Implementation

```python
from dexter_py.agent.orchestrator import Agent, AgentOptions
from dexter_py.utils.message_history import MessageHistory

history = MessageHistory(model='gpt-4')
agent = Agent(AgentOptions(model='gpt-4'))

# First query
answer1 = await agent.run('Analyze Apple\'s financials.', history)

# Manually build context for next query
context = history.format_for_planning()
enriched_query = f'{context}\n\nNow compare with Microsoft.'

answer2 = await agent.run(enriched_query, history)
```

**Benefits:**
- Full control over context inclusion
- Can cherry-pick specific messages
- Useful for specialized use cases

**Considerations:**
- Requires manual context management
- More verbose implementation

---

## MessageHistory API

### TypeScript

```typescript
class MessageHistory {
  // Add a complete conversation turn
  async addMessage(query: string, answer: string): Promise<void>

  // Check if history has messages
  hasMessages(): boolean

  // Get all messages
  getAll(): Message[]

  // Get most recent message
  last(): Message | undefined

  // Select relevant messages for current query
  async selectRelevantMessages(currentQuery: string): Promise<Message[]>

  // Format messages for inclusion in planning prompts
  formatForPlanning(messages?: Message[]): string

  // Format full history for context
  formatForContext(): string

  // Update model used for relevance scoring
  setModel(model: string): void

  // Clear all messages
  clear(): void
}

interface Message {
  id: number
  query: string
  answer: string
  summary: string // LLM-generated summary for relevance matching
}
```

### Python

```python
class MessageHistory:
    # Add complete conversation turn
    def add_agent_message(self, query: str, answer: str, summary: str = "") -> None

    # Check if messages exist
    def has_messages(self) -> bool

    # Get all messages
    def get_all(self) -> List[Message]

    # Get most recent message
    def last(self) -> Optional[Message]

    # Select relevant messages for current query
    async def select_relevant_messages(self, current_query: str) -> List[Message]

    # Format messages for inclusion in planning prompts
    def format_for_planning(self, messages: Optional[List[Message]] = None) -> str

    # Format full history for context inclusion
    def format_for_context(self) -> str

    # Update model for relevance scoring
    def set_model(self, model: str) -> None

    # Clear all messages
    def clear(self) -> None

@dataclass
class Message:
    id: int
    query: str
    answer: str
    summary: str  # LLM-generated summary
```

---

## Integration with Phases

All five agent phases now support conversation context:

### Phase 1: Understand
- Uses history to extract more accurate intent
- References previous queries to disambiguate entities
- Example: If user said "Apple" earlier, "What about their margins?" is understood in context

### Phase 2: Plan
- Incorporates prior conversation to avoid duplicating work
- Creates plans that reference previous findings
- Example: "Compare with the Microsoft data from the last query"

### Phase 3: Execute
- Executes tasks with awareness of prior data gathered
- May skip redundant tool calls based on history
- Example: Doesn't re-fetch Apple's P/E if already retrieved

### Phase 4: Reflect
- Evaluates if new data answers follow-up questions
- Reflects on conversation arc
- Example: "User asked about margins after P/E, so reflect on both"

### Phase 5: Answer
- Synthesizes answer with reference to previous discussion
- Provides comparative analysis when relevant
- Example: "Building on our earlier analysis of Apple, here's how Microsoft compares"

---

## CLI Usage

### TypeScript CLI

The interactive CLI automatically maintains conversation history:

```bash
bun run src/index.tsx

# Query 1: "What is Apple's P/E ratio?"
# Agent researches and responds

# Query 2: "What about their dividend yield?"
# Agent automatically includes context about Apple from Query 1

# Query 3: "Compare to Microsoft"
# Agent has context of all previous queries about Apple
```

### Python CLI

```bash
# Create a conversation in Python backend
python cli.py ask "What is Apple's P/E ratio?"
python cli.py ask "What about Microsoft?"

# Note: Each CLI invocation creates a new agent
# Use the FastAPI server for true multi-turn conversation
```

---

## API Server Usage

### FastAPI Backend

The Python backend API maintains conversation context per client session:

```python
# Client maintains a conversation session
session_history = MessageHistory(model='gpt-4')

# Multiple queries in same session
async with httpx.AsyncClient() as client:
    # Query 1
    response1 = await client.post(
        'http://localhost:8000/chat',
        json={'query': 'What is AAPL P/E?', 'session_id': 'user_123'}
    )
    
    # Query 2 - includes context from Query 1
    response2 = await client.post(
        'http://localhost:8000/chat',
        json={'query': 'What about MSFT?', 'session_id': 'user_123'}
    )
```

---

## Best Practices

### 1. Initialize Once Per Session
```typescript
// ✅ Good - agent persists across queries
const agent = new Agent({ model: 'gpt-4' });
await agent.run('Query 1');
await agent.run('Query 2');

// ❌ Bad - creates new agent for each query, loses context
const agent1 = new Agent({ model: 'gpt-4' });
await agent1.run('Query 1');
const agent2 = new Agent({ model: 'gpt-4' });
await agent2.run('Query 2');
```

### 2. Use External History for Multi-Agent Scenarios
```typescript
// ✅ Good - history persists across agents
const history = new MessageHistory();
const agent1 = new Agent({ model: 'gpt-4' });
const answer1 = await agent1.run('Query 1', history);

const agent2 = new Agent({ model: 'gpt-4' });
const answer2 = await agent2.run('Query 2', history);
```

### 3. Periodically Clear History for New Conversations
```typescript
// ✅ Good - start fresh conversation
const history = new MessageHistory();
// ... conversation continues
history.clear();  // Reset for new topic
```

### 4. Monitor History Size
```typescript
// ✅ Good - prevent unbounded growth
if (history.getAll().length > 50) {
  history.clear();
}
```

### 5. Set Model When Switching LLMs
```typescript
// ✅ Good - update model for relevance scoring
const history = new MessageHistory('gpt-4');
// ... use with GPT-4
history.setModel('claude-3-opus');
// ... continue with Claude
```

---

## Conversation Context Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Agent Initialized (with persistent message_history)         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Query 1: "What is Apple's P/E ratio?"                       │
│ ├─ Understand: Extract intent & entities (no prior context) │
│ ├─ Plan: Create task list                                   │
│ ├─ Execute: Fetch financial data                            │
│ ├─ Reflect: Data sufficient?                                │
│ └─ Answer: Synthesize response                              │
│ ↓ SAVED TO HISTORY                                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Query 2: "What about their dividend yield?"                 │
│ ├─ Understand: Extract intent using prior context           │
│ │  └─ Recognizes "their" refers to Apple                    │
│ ├─ Plan: Create task list (may skip P/E re-fetch)           │
│ ├─ Execute: Fetch dividend data                             │
│ ├─ Reflect: Data sufficient?                                │
│ └─ Answer: Synthesize with reference to previous analysis   │
│ ↓ SAVED TO HISTORY                                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Query 3: "Compare with Microsoft"                           │
│ ├─ Understand: Uses context of Apple discussion             │
│ ├─ Plan: Creates comparative analysis plan                  │
│ ├─ Execute: Fetches Microsoft data (reuses Apple data)      │
│ ├─ Reflect: Sufficient for comparison?                      │
│ └─ Answer: Comparative analysis with Apple context          │
│ ↓ SAVED TO HISTORY                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

### History Not Persisting Between Queries

**Problem:** Context is not available in subsequent queries.

**Solution:** Ensure you're using the same agent instance or passing the same MessageHistory:

```typescript
// ✅ Correct
const agent = new Agent({ model: 'gpt-4' });
await agent.run('Query 1');
await agent.run('Query 2');  // Has context

// ❌ Wrong
const agent1 = new Agent({ model: 'gpt-4' });
await agent1.run('Query 1');
const agent2 = new Agent({ model: 'gpt-4' });
await agent2.run('Query 2');  // No context
```

### History Too Large

**Problem:** Agent performance degrades with many conversation turns.

**Solution:** Periodically clear or summarize history:

```typescript
const history = agent.getMessageHistory();
if (history.getAll().length > 100) {
  // Keep only last 10 messages
  const messages = history.getAll();
  history.clear();
  messages.slice(-10).forEach(m => {
    history.addMessage(m.query, m.answer);
  });
}
```

### Model Change Breaks Relevance Scoring

**Problem:** Context selection works poorly after changing models.

**Solution:** Update the model in MessageHistory:

```typescript
const history = agent.getMessageHistory();
history.setModel('new-model-name');
```

---

## Summary

**Three Ways to Use Persistent Context:**

1. **Automatic (Recommended)**: Let Agent manage history - simplest approach
2. **Explicit Management**: Manage MessageHistory directly - for multi-agent scenarios
3. **Manual Construction**: Build context into prompts - maximum control

**Key Points:**
- History is automatically maintained across queries in same Agent instance
- History can be passed between Agent instances for true multi-session persistence
- All phases leverage conversation context for better understanding
- History follows a structured format for reliable context inclusion
- Best for interactive CLI and chat applications
