import { useState, useCallback, useRef } from 'react';
import { MessageHistory } from '../utils/message-history.js';
import { generateId } from '../cli/types.js';
import type { Task, Phase, TaskStatus, ToolCallStatus, Plan } from '../agent/state.js';
import type { AgentProgressState } from '../components/AgentProgressView.js';

// ============================================================================
// Types
// ============================================================================

/**
 * Current turn state for the agent.
 */
export interface CurrentTurn {
  id: string;
  query: string;
  state: AgentProgressState;
}

interface UseAgentExecutionOptions {
  model: string;
  messageHistory: MessageHistory;
}

/**
 * A tool error for debugging.
 */
export interface ToolError {
  taskId: string;
  toolName: string;
  args: Record<string, unknown>;
  error: string;
}

interface UseAgentExecutionResult {
  currentTurn: CurrentTurn | null;
  answerStream: AsyncGenerator<string> | null;
  isProcessing: boolean;
  toolErrors: ToolError[];
  processQuery: (query: string) => Promise<void>;
  handleAnswerComplete: (answer: string) => void;
  cancelExecution: () => void;
}

/**
 * Pending task update to be applied when tasks are available.
 */
interface PendingTaskUpdate {
  taskId: string;
  status: TaskStatus;
}

/**
 * Pending tool call update to be applied when tasks are available.
 */
interface PendingToolCallUpdate {
  taskId: string;
  toolIndex: number;
  status: ToolCallStatus['status'];
}

// ============================================================================
// Hook Implementation
// ============================================================================

/**
 * Hook that connects the agent to React state.
 * Manages phase transitions, task updates, and answer streaming.
 */
export function useAgentExecution({
  model,
  messageHistory,
}: UseAgentExecutionOptions): UseAgentExecutionResult {
  const [currentTurn, setCurrentTurn] = useState<CurrentTurn | null>(null);
  const [answerStream, setAnswerStream] = useState<AsyncGenerator<string> | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [toolErrors, setToolErrors] = useState<ToolError[]>([]);

  const currentQueryRef = useRef<string | null>(null);
  const isProcessingRef = useRef(false);
  
  // Track pending updates for race condition handling
  const pendingTaskUpdatesRef = useRef<PendingTaskUpdate[]>([]);
  const pendingToolCallUpdatesRef = useRef<PendingToolCallUpdate[]>([]);

  /**
   * Updates the current phase.
   */
  const setPhase = useCallback((phase: Phase) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        state: {
          ...prev.state,
          currentPhase: phase,
        },
      };
    });
  }, []);

  /**
   * Marks a phase as complete.
   */
  const markPhaseComplete = useCallback((phase: Phase) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      
      const updates: Partial<AgentProgressState> = {};
      
      switch (phase) {
        case 'understand':
          updates.understandComplete = true;
          break;
        case 'plan':
          updates.planComplete = true;
          break;
        case 'reflect':
          updates.reflectComplete = true;
          break;
      }
      
      return {
        ...prev,
        state: {
          ...prev.state,
          ...updates,
        },
      };
    });
  }, []);

  /**
   * Sets the task list after plan creation.
   * Applies any pending task/tool updates that arrived before tasks were set.
   */
  const setTasksFromPlan = useCallback((plan: Plan) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      
      // Start with plan tasks
      let tasks = [...plan.tasks];
      
      // Apply any pending task status updates
      const pendingTaskUpdates = pendingTaskUpdatesRef.current;
      for (const update of pendingTaskUpdates) {
        tasks = tasks.map(task =>
          task.id === update.taskId ? { ...task, status: update.status } : task
        );
      }
      pendingTaskUpdatesRef.current = [];
      
      // Apply any pending tool call status updates
      const pendingToolUpdates = pendingToolCallUpdatesRef.current;
      for (const update of pendingToolUpdates) {
        tasks = tasks.map(task => {
          if (task.id !== update.taskId || !task.toolCalls) return task;
          const toolCalls = task.toolCalls.map((tc, i) =>
            i === update.toolIndex ? { ...tc, status: update.status } : tc
          );
          return { ...task, toolCalls };
        });
      }
      pendingToolCallUpdatesRef.current = [];
      
      return {
        ...prev,
        state: {
          ...prev.state,
          tasks,
        },
      };
    });
  }, []);

  /**
   * Updates a task's status.
   * If tasks aren't set yet, queues the update for later.
   */
  const updateTaskStatus = useCallback((taskId: string, status: TaskStatus) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      
      // If tasks aren't set yet, queue the update
      if (prev.state.tasks.length === 0) {
        pendingTaskUpdatesRef.current.push({ taskId, status });
        return prev;
      }
      
      const tasks = prev.state.tasks.map(task => 
        task.id === taskId ? { ...task, status } : task
      );
      
      return {
        ...prev,
        state: {
          ...prev.state,
          tasks,
        },
      };
    });
  }, []);

  /**
   * Sets the tool calls for a task when they are first selected.
   */
  const setTaskToolCalls = useCallback((taskId: string, toolCalls: ToolCallStatus[]) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      
      const tasks = prev.state.tasks.map(task =>
        task.id === taskId ? { ...task, toolCalls } : task
      );
      
      return {
        ...prev,
        state: {
          ...prev.state,
          tasks,
        },
      };
    });
  }, []);

  /**
   * Updates a tool call's status within a task.
   * If tasks aren't set yet, queues the update for later.
   */
  const updateToolCallStatus = useCallback((
    taskId: string, 
    toolIndex: number, 
    status: ToolCallStatus['status']
  ) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      
      // If tasks aren't set yet, queue the update
      if (prev.state.tasks.length === 0) {
        pendingToolCallUpdatesRef.current.push({ taskId, toolIndex, status });
        return prev;
      }
      
      const tasks = prev.state.tasks.map(task => {
        if (task.id !== taskId || !task.toolCalls) return task;
        
        const toolCalls = task.toolCalls.map((tc, i) => 
          i === toolIndex ? { ...tc, status } : tc
        );
        
        return { ...task, toolCalls };
      });
      
      return {
        ...prev,
        state: {
          ...prev.state,
          tasks,
        },
      };
    });
  }, []);

  /**
   * Sets the answering state.
   */
  const setAnswering = useCallback((isAnswering: boolean) => {
    setCurrentTurn(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        state: {
          ...prev.state,
          isAnswering,
        },
      };
    });
  }, []);

  /**
   * Handles tool call errors for debugging.
   */
  const handleToolCallError = useCallback((
    taskId: string,
    _toolIndex: number,
    toolName: string,
    args: Record<string, unknown>,
    error: Error
  ) => {
    setToolErrors(prev => [...prev, { taskId, toolName, args, error: error.message }]);
  }, []);

  /**
   * Creates agent callbacks that update React state.
   */
  const createAgentCallbacks = useCallback((): AgentCallbacks => ({
    onPhaseStart: setPhase,
    onPhaseComplete: markPhaseComplete,
    onPlanCreated: setTasksFromPlan,
    onTaskUpdate: updateTaskStatus,
    onTaskToolCallsSet: setTaskToolCalls,
    onToolCallUpdate: updateToolCallStatus,
    onToolCallError: handleToolCallError,
    onAnswerStart: () => setAnswering(true),
    onAnswerStream: (stream) => setAnswerStream(stream),
  }), [setPhase, markPhaseComplete, setTasksFromPlan, updateTaskStatus, setTaskToolCalls, updateToolCallStatus, handleToolCallError, setAnswering]);

  /**
   * Handles the completed answer.
   */
  const handleAnswerComplete = useCallback((answer: string) => {
    setCurrentTurn(null);
    setAnswerStream(null);

    // Add to message history for multi-turn context
    const query = currentQueryRef.current;
    if (query && answer) {
      messageHistory.addMessage(query, answer).catch(() => {
        // Silently ignore errors in adding to history
      });
    }
    currentQueryRef.current = null;
  }, [messageHistory]);

  /**
   * Processes a single query through the agent.
   */
  const processQuery = useCallback(
    async (query: string): Promise<void> => {
      if (isProcessingRef.current) return;
      isProcessingRef.current = true;
      setIsProcessing(true);

      // Store current query for message history
      currentQueryRef.current = query;

      // Clear any pending updates and errors from previous run
      pendingTaskUpdatesRef.current = [];
      pendingToolCallUpdatesRef.current = [];
      setToolErrors([]);

      // Initialize simple turn state for frontend display
      setCurrentTurn({
        id: generateId(),
        query,
        state: {
          currentPhase: 'understand',
          understandComplete: true,
          planComplete: true,
          reflectComplete: true,
          tasks: [],
          isAnswering: true,
        },
      });

      try {
        // Send the prompt to the Python backend at /query
        const res = await fetch('http://localhost:8000/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: query }),
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Backend error: ${res.status} ${text}`);
        }

        // Try to stream the response if possible, else read full text
        let answerText: string;
        try {
          // Some runtimes provide a readable stream
          const reader = (res.body as unknown as ReadableStream<Uint8Array>).getReader();
          const decoder = new TextDecoder();
          let done = false;
          let buffer = '';

          async function* streamGenerator() {
            while (!done) {
              // eslint-disable-next-line no-await-in-loop
              const { value, done: d } = await reader.read();
              if (value) {
                buffer += decoder.decode(value, { stream: true });
                yield buffer;
              }
              if (d) {
                done = true;
                break;
              }
            }
            // Final chunk
            if (buffer) yield buffer;
          }

          // Use the async generator as the answerStream
          setAnswerStream(streamGenerator());
          // Consume final value for message history
          let final = '';
          for await (const chunk of streamGenerator()) {
            final = chunk;
          }
          answerText = final;
        } catch (e) {
          // Fallback: read as JSON then extract response
          const data = await res.json();
          answerText = typeof data.response === 'string' ? data.response : JSON.stringify(data.response);
          // Provide a simple non-streaming response to the UI
          setAnswerStream((async function* () { yield answerText; })());
        }

        // Finalize
        // Add to message history for multi-turn context
        if (currentQueryRef.current && answerText) {
          try {
            await messageHistory.addMessage(currentQueryRef.current, answerText);
          } catch (_err) {
            // ignore
          }
        }

      } catch (err) {
        setCurrentTurn(null);
        currentQueryRef.current = null;
        throw err;
      } finally {
        isProcessingRef.current = false;
        setIsProcessing(false);
      }
    },
    [model, messageHistory, createAgentCallbacks]
  );

  /**
   * Cancels the current execution.
   */
  const cancelExecution = useCallback(() => {
    setCurrentTurn(null);
    setAnswerStream(null);
    isProcessingRef.current = false;
    setIsProcessing(false);
  }, []);

  return {
    currentTurn,
    answerStream,
    isProcessing,
    toolErrors,
    processQuery,
    handleAnswerComplete,
    cancelExecution,
  };
}
