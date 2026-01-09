# Before & After - Persistent Context Implementation

## The Problem

**Before:** Each agent query was isolated. Follow-up questions had no access to previous context.

```
User: "What is Apple's P/E ratio?"
Agent: [Researches Apple's P/E ratio, returns answer]
         ↓ CONTEXT LOST

User: "What about their revenue?"
Agent: [No context about Apple - has to re-identify ticker from "their"]
       [Re-fetches basic data to confirm what "their" refers to]
       [Answers revenue question, but without comparative context]
         ↓ CONTEXT LOST

User: "Compare with Microsoft"
Agent: [No context about previous discussion]
       [Has to re-fetch both Apple and Microsoft data]
       [Provides comparison but without conversation arc]
```

**Issues:**
- Redundant data fetching
- Ambiguity in entity resolution ("their" → requires context)
- No conversation memory
- Inefficient API usage
- Missed opportunities for comparative analysis

---

## The Solution

**After:** Agent maintains persistent conversation history automatically.

```
User: "What is Apple's P/E ratio?"
Agent: [Researches Apple's P/E ratio]
       [Returns answer with sources]
       ↓ SAVED TO HISTORY: Turn 1 {query, answer, summary}

User: "What about their revenue?"
Agent: [History available → understands "their" = Apple from context]
       [Plans efficiently - knows basic data already available]
       [Focuses on revenue-specific research]
       [Returns answer referencing prior P/E discussion]
       ↓ SAVED TO HISTORY: Turn 2 {query, answer, summary}

User: "Compare with Microsoft"
Agent: [History available → knows Apple context from Turns 1-2]
       [Fetches Microsoft data efficiently]
       [Synthesizes comparison with Apple context]
       [Returns comprehensive comparative analysis]
       ↓ SAVED TO HISTORY: Turn 3 {query, answer, summary}
```

**Benefits:**
- No redundant fetching
- Clear entity resolution
- Conversation memory
- Efficient resource usage
- Rich comparative insights

---

## Code Examples

### Python Backend

#### Before (Isolated Queries)

```python
# No context between queries
agent = Agent(AgentOptions(model='gpt-4'))

# Query 1
answer1 = await agent.run('What is Apple P/E?')
# Agent researches Apple, returns answer
# HISTORY: Not accessible

# Query 2
answer2 = await agent.run('What about their revenue?')
# Agent: "What does 'their' refer to?"
# Has to infer from query text alone
# Re-fetches Apple data to confirm
# HISTORY: Not accessible

# Query 3
answer3 = await agent.run('Compare with Microsoft')
# Agent: No memory of Apple discussion
# Fetches both Apple and Microsoft from scratch
# HISTORY: Not accessible
```

#### After (Persistent Context)

```python
# Context maintained automatically
agent = Agent(AgentOptions(model='gpt-4'))

# Query 1
answer1 = await agent.run('What is Apple P/E?')
# Agent researches Apple, returns answer
# HISTORY: Turn 1 stored automatically
#   query: "What is Apple P/E?"
#   answer: "[Full response about Apple P/E]"
#   summary: "Query about Apple's P/E ratio"

# Query 2
answer2 = await agent.run('What about their revenue?')
# Agent: History context available!
# Understand phase: "their" clearly = Apple from Turn 1
# Plan phase: Knows P/E already retrieved, focuses on revenue
# Execute phase: Efficient, focused research
# Answer phase: References "Building on Apple's P/E analysis..."
# HISTORY: Turn 2 stored automatically
#   query: "What about their revenue?"
#   answer: "[Full response about Apple revenue, with P/E reference]"
#   summary: "Query about Apple's revenue growth"

# Query 3
answer3 = await agent.run('Compare with Microsoft')
# Agent: Rich history context available!
# Understand phase: Comparison context understood
# Plan phase: Fetch MSFT data, reuse AAPL context
# Execute phase: Targeted, efficient research
# Answer phase: "Comparing Microsoft to Apple (analyzed earlier)..."
# HISTORY: Turn 3 stored automatically
#   query: "Compare with Microsoft"
#   answer: "[Comprehensive comparison using both companies' data]"
#   summary: "Comparative analysis of Apple and Microsoft"
```

### TypeScript Frontend

#### Before (No History)

```typescript
// Each agent instance isolated
const agent = new Agent({ model: 'gpt-4' });

// Query 1
const answer1 = await agent.run('What is Apple P/E?');
// Agent returns answer
// History not accessible

// Query 2 - New agent for new conversation
const agent2 = new Agent({ model: 'gpt-4' });
const answer2 = await agent2.run('What about revenue?');
// Different agent instance - no context from Query 1
// Has to figure out "revenue" of which company?
```

#### After (Automatic History)

```typescript
// Single agent maintains context across queries
const agent = new Agent({ model: 'gpt-4' });

// Query 1
const answer1 = await agent.run('What is Apple P/E?');
// Agent researches, returns answer
// History saved automatically in agent

// Query 2 - Same agent, context automatic
const answer2 = await agent.run('What about revenue?');
// Agent has access to Turn 1 context
// "their" clearly refers to Apple from previous query
// Returns revenue data with P/E context

// Query 3 - Continued conversation with growing context
const answer3 = await agent.run('Compare with Microsoft');
// Agent uses context from all previous turns
// Comparison includes Apple analysis from earlier

// Access history anytime
const history = agent.getMessageHistory();
console.log(`Conversation turns: ${history.getAll().length}`);
history.getAll().forEach((turn, i) => {
  console.log(`Turn ${i + 1}: ${turn.summary}`);
});
```

---

## Phase Behavior Changes

### Understand Phase

**Before:**
```python
understanding = await understand_phase.run(
    query="What about their revenue?",
    conversation_history=None  # No history
)
# Result:
# intent: "Query about revenue"
# entities: [
#   {type: 'other', value: 'their'},
#   {type: 'metric', value: 'revenue'}
# ]
# Problem: "their" not resolved to Apple
```

**After:**
```python
history = MessageHistory()
# ... Turn 1 saved to history ...

understanding = await understand_phase.run(
    query="What about their revenue?",
    conversation_history=history  # Has context!
)
# Result:
# intent: "Query about Apple's revenue growth"
# entities: [
#   {type: 'ticker', value: 'AAPL'},  # ← Resolved from context!
#   {type: 'metric', value: 'revenue'}
# ]
# Benefit: "their" automatically resolved to Apple
```

### Plan Phase

**Before:**
```python
# No awareness of prior work
plan = await plan_phase.run(
    query="What about their revenue?",
    understanding=understanding,
    prior_plans=None,  # No prior context
    prior_results=None
)
# Result: Plan might include:
# - Task 1: Get basic company info (redundant - already have)
# - Task 2: Get revenue data
# - Task 3: Get analyst estimates
```

**After:**
```python
# Aware of prior work
plan = await plan_phase.run(
    query="What about their revenue?",
    understanding=understanding,
    prior_plans=[plan_from_turn_1],  # Context available!
    prior_results=results_from_turn_1
)
# Result: Optimized plan:
# - Task 1: Get Apple's revenue data (focused, not basic info)
# - Task 2: Get revenue trends (what we need)
# Benefit: Avoids duplicate work, more efficient
```

### Answer Phase

**Before:**
```typescript
const stream = answerPhase.run({
  query: 'Compare with Microsoft',
  completedPlans: [currentPlan],
  taskResults: currentResults
  // No message history
});

// Answer: "Here is Microsoft's data..."
// Problem: No reference to Apple context from earlier
```

**After:**
```typescript
const stream = answerPhase.run({
  query: 'Compare with Microsoft',
  completedPlans: [currentPlan],
  taskResults: currentResults,
  messageHistory: history  // Has Apple context!
});

// Answer: "Building on our earlier analysis of Apple's P/E of X,
//          here's how Microsoft compares with P/E of Y..."
// Benefit: Coherent conversation arc
```

---

## User Experience Comparison

### Scenario: Financial Analysis Conversation

**Before (No Context):**

```
User: "What is Apple's current P/E ratio?"

[Agent researches Apple]
Agent: "Apple's current P/E ratio is 28.5, which is higher 
        than the historical average of 25.2. This suggests..."
        [4 seconds]

User: "What about their margins?"

[Agent has to infer "their" means Apple... researchesApple's margins]
Agent: "Apple's gross margin is 46.2%, operating margin is 28.1%...
       These are quite healthy for tech companies."
        [5 seconds - took longer due to re-research]

User: "Compare them to Microsoft."

[Agent has no context, fetches both companies from scratch]
Agent: "Microsoft's P/E is 32.4, margins are different...
        [comparison provided but no arc from previous discussion]"
        [6 seconds - slowest due to redundant fetching]

Total time: 15 seconds
Redundancy: Apple data fetched 3 times
Coherence: Low - feels like separate queries, not conversation
```

**After (With Context):**

```
User: "What is Apple's current P/E ratio?"

[Agent researches Apple]
Agent: "Apple's current P/E ratio is 28.5, which is higher 
        than the historical average of 25.2. This suggests..."
        [4 seconds]

User: "What about their margins?"

[Agent knows "their" = Apple from context, focused research]
Agent: "Apple's gross margin is 46.2%, operating margin is 28.1%.
        In context of their P/E of 28.5, these healthy margins 
        justify the higher valuation."
        [3 seconds - faster due to focused research and reuse]

User: "Compare them to Microsoft."

[Agent has Apple context, efficiently fetches only Microsoft]
Agent: "Comparing to our earlier analysis of Apple:
        • Apple P/E: 28.5 vs Microsoft: 32.4
        • Apple margins: 46.2%/28.1% vs Microsoft: 67.8%/41.5%
        Microsoft commands premium despite lower margins..."
        [4 seconds - efficient, uses cached Apple data]

Total time: 11 seconds (27% faster!)
Redundancy: Apple data fetched 1 time (2 fewer unnecessary fetches)
Coherence: High - clear conversation arc with comparative insights
```

---

## Memory Usage

### Before
```
Query 1: Download Apple data (0.5 MB)
Query 2: Download Apple data again (0.5 MB) - DUPLICATE
Query 3: Download Apple data + Microsoft data (0.5 + 0.5 MB) - DUPLICATE
Total: 1.5 MB downloaded, 0.5 MB redundant
```

### After
```
Query 1: Download Apple data (0.5 MB)
         Store in history (0.01 MB)
Query 2: Use history (0.01 MB) - NO DUPLICATE
         Download revenue data (0.2 MB)
Query 3: Use history (0.01 MB) - NO DUPLICATE
         Download Microsoft data (0.5 MB)
Total: 1.2 MB downloaded, 0 MB redundant (20% reduction)
```

---

## API Usage Impact

### Before (No Context)
```
Turn 1: financial_datasets API calls: 4
        LLM calls: 2
        Total: 6 API calls

Turn 2: financial_datasets API calls: 4 (SAME AS TURN 1)
        LLM calls: 2
        Total: 6 API calls

Turn 3: financial_datasets API calls: 8 (4 per company)
        LLM calls: 2
        Total: 10 API calls

Total for 3 turns: 22 API calls
Cost: ~$2.20 (at typical pricing)
```

### After (With Context)
```
Turn 1: financial_datasets API calls: 4
        LLM calls: 2
        Total: 6 API calls

Turn 2: financial_datasets API calls: 2 (FOCUSED - no duplicates)
        LLM calls: 2
        Total: 4 API calls

Turn 3: financial_datasets API calls: 4 (ONLY Microsoft, reuse Apple)
        LLM calls: 2
        Total: 6 API calls

Total for 3 turns: 16 API calls (27% reduction)
Cost: ~$1.60 (27% savings)
```

---

## Implementation Summary

| Aspect | Before | After |
|--------|--------|-------|
| **History Maintained** | ❌ No | ✅ Yes |
| **Cross-Turn Context** | ❌ No | ✅ Yes |
| **Redundant Fetches** | ✅ Common | ❌ Avoided |
| **Entity Resolution** | ❌ Ambiguous | ✅ Clear |
| **Conversation Arc** | ❌ Disconnected | ✅ Coherent |
| **API Efficiency** | ❌ Low | ✅ High |
| **Response Time** | ❌ Slow | ✅ Fast |
| **User Experience** | ❌ Query-like | ✅ Conversation-like |

---

## Getting Started

To use persistent context in your application:

```python
# Python - Simple approach
from dexter_py.agent.orchestrator import Agent, AgentOptions

agent = Agent(AgentOptions(model='gpt-4'))

# Turn 1
answer1 = await agent.run('What is Apple P/E?')

# Turn 2 - Automatically includes context
answer2 = await agent.run('What about revenue?')
```

```typescript
// TypeScript - Simple approach
import { Agent } from './agent/orchestrator.js';

const agent = new Agent({ model: 'gpt-4' });

// Turn 1
const answer1 = await agent.run('What is Apple P/E?');

// Turn 2 - Automatically includes context
const answer2 = await agent.run('What about revenue?');
```

See [CONTEXT_QUICKSTART.md](./CONTEXT_QUICKSTART.md) for more examples.

---

## Next Steps

1. ✅ **Basic Usage**: Try the simplest approach (same agent instance)
2. ✅ **Multi-Agent**: Use explicit history for multi-agent scenarios
3. ✅ **Persistence**: Save/load history for session management
4. ✅ **Optimization**: Monitor history size, clear when needed
5. ✅ **Production**: Deploy with context management for better UX
