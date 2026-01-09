# Persistent Context - Quick Start

## Simplest Approach (One Agent Instance)

### TypeScript
```typescript
const agent = new Agent({ model: 'gpt-4' });

// Turn 1
const answer1 = await agent.run('What is Apple\'s current P/E ratio?');

// Turn 2 - Automatically includes context from Turn 1
const answer2 = await agent.run('What about their revenue growth?');

// Turn 3 - Has context from both previous turns
const answer3 = await agent.run('Compare with Microsoft\'s metrics');
```

### Python
```python
agent = Agent(AgentOptions(model='gpt-4'))

# Turn 1
answer1 = await agent.run('What is Apple\'s current P/E ratio?')

# Turn 2 - Automatically includes context from Turn 1
answer2 = await agent.run('What about their revenue growth?')

# Turn 3 - Has context from both previous turns
answer3 = await agent.run('Compare with Microsoft\'s metrics')
```

## Multi-Agent with Shared History

### TypeScript
```typescript
const history = new MessageHistory('gpt-4');

// Agent 1
const agent1 = new Agent({ model: 'gpt-4' });
await agent1.run('Analyze AAPL financials', history);

// Agent 2 - Reuses history from Agent 1
const agent2 = new Agent({ model: 'gpt-4' });
await agent2.run('What about MSFT?', history);

// Switch models, keep history
const agent3 = new Agent({ model: 'claude-3-opus' });
await agent3.run('Compare them', history);
```

### Python
```python
history = MessageHistory(model='gpt-4')

# Agent 1
agent1 = Agent(AgentOptions(model='gpt-4'))
await agent1.run('Analyze AAPL financials', history)

# Agent 2 - Reuses history from Agent 1
agent2 = Agent(AgentOptions(model='gpt-4'))
await agent2.run('What about MSFT?', history)

# Switch models, keep history
history.set_model('claude-3-opus')
agent3 = Agent(AgentOptions(model='claude-3-opus'))
await agent3.run('Compare them', history)
```

## How It Works

**Approach 1: Automatic (Recommended)**
- Agent creates its own `MessageHistory`
- Each `agent.run()` automatically saves query+answer
- Next `agent.run()` passes history automatically
- **Best for**: CLI, interactive apps, single-session conversations

**Approach 2: Explicit (For APIs)**
- Create `MessageHistory` once per session
- Pass same history to multiple agents or queries
- History survives agent recreation
- **Best for**: Web APIs, multi-agent systems, persistent sessions

**Approach 3: Manual (Maximum Control)**
- Build context string yourself from history
- Include in query or system prompt
- Full control over what context is used
- **Best for**: Specialized workflows, debugging

## What Gets Saved

Each conversation turn saves:
```typescript
interface Message {
  id: number              // Sequential turn number
  query: string           // User's question
  answer: string          // Agent's full response
  summary: string         // AI-generated summary for matching
}
```

## Context Usage in Each Phase

| Phase | Uses History For | Example |
|-------|------------------|---------|
| **Understand** | Disambiguate entities | "Their margins" → understands "Apple" from prior context |
| **Plan** | Avoid duplicate work | Doesn't re-fetch P/E if already retrieved |
| **Execute** | Smart tool selection | Knows which data already exists |
| **Reflect** | Continuity check | Evaluates progress on multi-part question |
| **Answer** | Comparative synthesis | Includes comparisons to prior discussions |

## Accessing History

```typescript
// Get agent's history
const history = agent.getMessageHistory();

// Check if has messages
if (history.hasMessages()) {
  // Get all messages
  const messages = history.getAll();
  
  // Get last message
  const lastTurn = history.last();
  
  // Format for context
  const context = history.formatForPlanning();
}

// Clear history (start fresh)
history.clear();
```

```python
# Get agent's history
history = agent.message_history

# Check if has messages
if history.has_messages():
    # Get all messages
    messages = history.get_all()
    
    # Get last message
    last_turn = history.last()
    
    # Format for context
    context = history.format_for_planning()

# Clear history (start fresh)
history.clear()
```

## Multi-Turn Example

```typescript
// Create agent - persists history automatically
const agent = new Agent({
  model: 'gpt-4',
  callbacks: {
    onAnswerStart: () => console.log('Generating answer...'),
    onPhaseComplete: (phase) => console.log(`${phase} complete`),
  }
});

// Turn 1: User asks about Apple
console.log('User: What is Apple\'s P/E ratio?');
const answer1 = await agent.run('What is Apple\'s P/E ratio?');
console.log(`Agent: ${answer1}\n`);

// Turn 2: Agent knows we're talking about Apple
console.log('User: How about their debt-to-equity ratio?');
const answer2 = await agent.run('How about their debt-to-equity ratio?');
console.log(`Agent: ${answer2}\n`);

// Turn 3: Agent can make comparisons
console.log('User: Compare Apple to Microsoft');
const answer3 = await agent.run('Compare Apple to Microsoft');
console.log(`Agent: ${answer3}\n`);

// Get conversation summary
const history = agent.getMessageHistory();
console.log(`\nConversation Summary:`);
history.getAll().forEach((msg, i) => {
  console.log(`Turn ${i + 1}: ${msg.summary}`);
});
```

## Common Patterns

### Pattern 1: Session-Based (Web API)
```typescript
// Handler for new user session
app.post('/chat/start', (req, res) => {
  const sessionId = generateId();
  const history = new MessageHistory('gpt-4');
  sessions.set(sessionId, history);
  res.json({ sessionId });
});

// Handler for user message
app.post('/chat/message', async (req, res) => {
  const { sessionId, query } = req.body;
  const history = sessions.get(sessionId);
  
  const agent = new Agent({ model: 'gpt-4' });
  const answer = await agent.run(query, history);
  
  res.json({ answer });
});
```

### Pattern 2: Dialog System
```typescript
// Maintain conversation loop
async function dialogLoop() {
  const agent = new Agent({ model: 'gpt-4' });
  
  while (true) {
    const userQuery = await getUserInput();
    const answer = await agent.run(userQuery);
    console.log(`Agent: ${answer}`);
    
    // History automatically grows with each turn
  }
}
```

### Pattern 3: Batch Processing with Context
```typescript
// Process multiple related queries in sequence
const agent = new Agent({ model: 'gpt-4' });
const history = agent.getMessageHistory();

for (const query of relatedQueries) {
  const answer = await agent.run(query);
  // Each query automatically gets context from previous ones
}
```

## Tips & Tricks

### Reuse History Across Sessions
```typescript
// Save history to JSON
const history = agent.getMessageHistory();
const json = JSON.stringify(history.getAll());
fs.writeFileSync('conversation.json', json);

// Load history in new session
const saved = JSON.parse(fs.readFileSync('conversation.json'));
const newHistory = new MessageHistory('gpt-4');
saved.forEach(msg => newHistory.addMessage(msg.query, msg.answer));
```

### Manual Context Injection
```typescript
// For very specific control over context
const history = agent.getMessageHistory();
const previousContext = history.formatForContext();

const enrichedQuery = `
${previousContext}

New question: ${userQuery}
`;

const answer = await agent.run(enrichedQuery);
```

### Monitor Conversation Growth
```typescript
const history = agent.getMessageHistory();

setInterval(() => {
  const turn = history.getAll().length;
  console.log(`Conversation turn: ${turn}`);
  
  if (turn > 20) {
    console.log('Long conversation - consider summarizing');
  }
}, 1000);
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Context not available next turn | Use same agent instance or pass MessageHistory to run() |
| Agent seems slow with old conversations | Clear history or summarize after N turns |
| Model change breaks context | Call `history.setModel(newModelName)` |
| Need to inspect what was saved | Use `history.getAll()` to see all messages |
| Want to start fresh conversation | Call `history.clear()` |
| Need conversation transcript | Use `history.formatForContext()` |

## Performance Considerations

- **History size**: Each message stored in memory
- **Context window**: LLM context size limits how much history can be included
- **Recommendation**: Clear history after 50+ turns for optimal performance
- **API calls**: Relevance scoring may make extra LLM calls (cached)

## Next Steps

1. Start with **Approach 1** (automatic agent history)
2. Move to **Approach 2** if you need multi-agent scenarios
3. Use **Approach 3** only for specialized cases

See [CONVERSATION_CONTEXT.md](./CONVERSATION_CONTEXT.md) for detailed documentation.
