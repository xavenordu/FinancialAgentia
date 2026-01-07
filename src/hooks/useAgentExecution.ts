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

interface SSETokenEvent {
  token: string;
  role?: string;
  request_id?: string;
}

interface UseAgentExecutionResult {
  currentTurn: CurrentTurn | null;
  answerStream: AsyncGenerator<SSETokenEvent> | null;
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
  const [answerStream, setAnswerStream] = useState<AsyncGenerator<SSETokenEvent> | null>(null);
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
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        // If a backend API key or bearer token is provided in the environment, include it.
        // Bundlers typically expose env vars via process.env.
        // For production, inject secrets via a secure mechanism rather than bundling.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const env: any = (typeof process !== 'undefined' ? (process as any).env : undefined) || {};
        if (env && env.BACKEND_API_KEY) {
          headers['X-API-Key'] = env.BACKEND_API_KEY;
        }
        if (env && env.AUTH_BEARER) {
          headers['Authorization'] = `Bearer ${env.AUTH_BEARER}`;
        }

        const res = await fetch('http://localhost:8000/query', {
          method: 'POST',
          headers,
          body: JSON.stringify({ prompt: query }),
        });

        if (!res.ok) {
          const text = await res.text();
          throw new Error(`Backend error: ${res.status} ${text}`);
        }

        // Try to stream the response if possible, else read full text
        let answerText: string;
        try {
          const decoder = new TextDecoder();

          // Push-based queue so we can (a) provide an async generator to the UI
          // and (b) also accumulate the full answer for message history.
          const queue: SSETokenEvent[] = [];
          let resolveNext: (() => void) | null = null;
          let finished = false;
          let finalParts: string[] = [];
          let finishResolve: (() => void) | null = null;
          const finishedPromise = new Promise<void>((r) => { finishResolve = r; });

          const pushToken = (item: SSETokenEvent | string) => {
            const ev: SSETokenEvent = typeof item === 'string' ? { token: item } : item;
            queue.push(ev);
            finalParts.push(ev.token);
            if (resolveNext) {
              resolveNext();
              resolveNext = null;
            }
          };

          const endQueue = () => {
            finished = true;
            if (resolveNext) {
              resolveNext();
              resolveNext = null;
            }
            if (finishResolve) finishResolve();
          };

          // Background reader loop: parse SSE events and push tokens.
          (async () => {
            try {
              let buffer = '';
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const body: any = (res as any).body;
              if (body && typeof body.getReader === 'function') {
                // Browser-style ReadableStream
                const webReader = body.getReader();
                while (true) {
                  // eslint-disable-next-line no-await-in-loop
                  const { value, done: d } = await webReader.read();
                  if (value) {
                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop() || '';
                    for (const part of parts) {
                      const lines = part.split('\n').map((l) => l.trim());
                      const dataLines = lines.filter((l) => l.startsWith('data:'));
                      if (dataLines.length === 0) continue;
                      const dataStr = dataLines.map((l) => l.replace(/^data:\s?/, '')).join('\n');
                      try {
                        const obj = JSON.parse(dataStr);
                        if (obj && typeof obj === 'object') {
                          if (obj.token) {
                            pushToken({ token: String(obj.token), role: obj.role, request_id: obj.request_id });
                          } else if (typeof obj === 'string') {
                            pushToken({ token: obj });
                          } else if (obj.error) {
                            pushToken({ token: `[ERROR] ${String(obj.error)}` });
                          }
                        }
                      } catch (_err) {
                        if (dataStr) pushToken({ token: dataStr });
                      }
                    }
                  }
                  if (d) break;
                }
              } else if (body && typeof body[Symbol.asyncIterator] === 'function') {
                // Node-style async iterator over Buffer/Uint8Array chunks
                // eslint-disable-next-line no-restricted-syntax
                for await (const chunk of body) {
                  buffer += decoder.decode(chunk, { stream: true } as any);
                  const parts = buffer.split('\n\n');
                  buffer = parts.pop() || '';
                  for (const part of parts) {
                    const lines = part.split('\n').map((l) => l.trim());
                    const dataLines = lines.filter((l) => l.startsWith('data:'));
                    if (dataLines.length === 0) continue;
                    const dataStr = dataLines.map((l) => l.replace(/^data:\s?/, '')).join('\n');
                    try {
                      const obj = JSON.parse(dataStr);
                      if (obj && typeof obj === 'object') {
                        if (obj.token) {
                          pushToken({ token: String(obj.token), role: obj.role, request_id: obj.request_id });
                        } else if (typeof obj === 'string') {
                          pushToken({ token: obj });
                        } else if (obj.error) {
                          pushToken({ token: `[ERROR] ${String(obj.error)}` });
                        }
                      }
                    } catch (_err) {
                      if (dataStr) pushToken({ token: dataStr });
                    }
                  }
                }
              } else {
                // No readable body available
                pushToken({ token: '[NO_BODY]' });
              }
            } catch (err) {
              try { pushToken({ token: `[STREAM_ERROR] ${String(err)}` }); } catch (_) {}
            } finally {
              endQueue();
            }
          })();

          // Async generator exposes tokens to the UI

          async function* streamGenerator() {
            while (!finished || queue.length > 0) {
              if (queue.length === 0) {
                // wait for next push
                await new Promise<void>((res) => { resolveNext = res; });
                continue;
              }
              yield queue.shift()!;
            }
          }

          const gen = streamGenerator();
          setAnswerStream(gen);

          // Wait for the reader to finish, then assemble final answer
          await finishedPromise;
          answerText = finalParts.join('');
        } catch (e) {
          // Fallback: read as JSON then extract response
          const data = await res.json();
          answerText = typeof data.response === 'string' ? data.response : JSON.stringify(data.response);
          // Provide a simple non-streaming response to the UI (SSETokenEvent)
          setAnswerStream((async function* () { yield { token: answerText }; })());
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
