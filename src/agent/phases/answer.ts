import { callLlmStream } from '../../model/llm.js';
import { getFinalAnswerSystemPrompt, buildFinalAnswerUserPrompt } from '../prompts.js';
import type { AnswerInput } from '../state.js';
import type { ToolContextManager } from '../../utils/context.js';
import type { MessageHistory } from '../../utils/message-history.js';

// ============================================================================
// Answer Phase Options
// ============================================================================

export interface AnswerPhaseOptions {
  model: string;
  contextManager: ToolContextManager;
}

// ============================================================================
// Answer Phase
// ============================================================================

/**
 * Generates the final answer from all task results across all iterations.
 * Optionally includes conversation history for multi-turn context awareness.
 */
export class AnswerPhase {
  private readonly model: string;
  private readonly contextManager: ToolContextManager;

  constructor(options: AnswerPhaseOptions) {
    this.model = options.model;
    this.contextManager = options.contextManager;
  }

  /**
   * Runs answer generation and returns a stream for the response.
   * Includes conversation context if messageHistory is provided.
   */
  async *run(input: AnswerInput): AsyncGenerator<string> {
    // Format task outputs from ALL plans
    const taskOutputs = input.completedPlans
      .flatMap(plan => plan.tasks)
      .map(task => {
        const result = input.taskResults.get(task.id);
        const output = result?.output ?? 'No output';
        return `Task: ${task.description}\nOutput: ${output}`;
      })
      .join('\n\n---\n\n');

    // Collect sources from context manager
    const queryId = this.contextManager.hashQuery(input.query);
    const pointers = this.contextManager.getPointersForQuery(queryId);
    
    const sources = pointers
      .filter(p => p.sourceUrls && p.sourceUrls.length > 0)
      .map(p => ({
        description: p.toolDescription,
        urls: p.sourceUrls!,
      }));

    const sourcesStr = sources.length > 0
      ? sources.map(s => `${s.description}: ${s.urls.join(', ')}`).join('\n')
      : '';

    // Build conversation context if history is provided
    let conversationContext = '';
    if (input.messageHistory && input.messageHistory.hasMessages()) {
      // Format relevant messages for context
      const relevantMessages = await input.messageHistory.selectRelevantMessages(input.query);
      if (relevantMessages.length > 0) {
        conversationContext = input.messageHistory.formatForPlanning(relevantMessages);
      }
    }

    // Build the final answer prompt with optional conversation context
    const systemPrompt = getFinalAnswerSystemPrompt();
    const userPrompt = this.buildPromptWithContext(
      input.query,
      taskOutputs,
      sourcesStr,
      conversationContext
    );

    // Return the stream
    yield* callLlmStream(userPrompt, {
      systemPrompt,
      model: this.model,
    });
  }

  /**
   * Builds the user prompt with optional conversation context.
   */
  private buildPromptWithContext(
    query: string,
    taskOutputs: string,
    sourcesStr: string,
    conversationContext: string
  ): string {
    const parts: string[] = [];

    if (conversationContext) {
      parts.push(conversationContext);
      parts.push('\n\n---\n\n');
    }

    parts.push(buildFinalAnswerUserPrompt(query, taskOutputs, sourcesStr));

    return parts.join('');
  }
}

