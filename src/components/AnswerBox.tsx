import React, { useState, useEffect, useRef } from 'react';
import { Box, Text } from 'ink';
import { colors } from '../theme.js';

interface SSETokenEvent {
  token: string;
  role?: string;
  request_id?: string;
}

interface AnswerBoxProps {
  stream?: AsyncGenerator<string> | AsyncGenerator<SSETokenEvent>;
  text?: string;
  onStart?: () => void;
  onComplete?: (answer: string) => void;
}

export const AnswerBox = React.memo(function AnswerBox({ stream, text, onStart, onComplete }: AnswerBoxProps) {
  const [content, setContent] = useState(text || '');
  const [isStreaming, setIsStreaming] = useState(!!stream);

  // Store callbacks in refs to avoid effect re-runs when references change
  const onStartRef = useRef(onStart);
  const onCompleteRef = useRef(onComplete);
  onStartRef.current = onStart;
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (!stream) return;

    let collected = text || '';
    let started = false;
    
    (async () => {
      try {
        for await (const chunk of stream as AsyncGenerator<any>) {
          try {
            // Log the raw chunk for debugging
            // eslint-disable-next-line no-console
            console.debug('AnswerBox received chunk:', chunk);
          } catch (_) {}

          let piece = '';
          if (typeof chunk === 'string') {
            piece = chunk;
          } else if (chunk && typeof chunk === 'object' && 'token' in chunk) {
            piece = String((chunk as SSETokenEvent).token || '');
            // Also log metadata if present
            try {
              // eslint-disable-next-line no-console
              console.debug('AnswerBox chunk meta:', { role: (chunk as SSETokenEvent).role, request_id: (chunk as SSETokenEvent).request_id });
            } catch (_) {}
          } else {
            piece = String(chunk || '');
          }

          if (!started && piece.trim()) {
            started = true;
            onStartRef.current?.();
          }

          collected += piece;
          setContent(collected);
        }
      } catch (err) {
        // Log streaming errors so the user can see them in the terminal
        // eslint-disable-next-line no-console
        console.error('AnswerBox stream error:', err);
        throw err;
      } finally {
        setIsStreaming(false);
        onCompleteRef.current?.(collected);
      }
    })();
  }, [stream, text]);

  return (
    <Box flexDirection="column" marginTop={1}>
      <Text>
        {content}
        {isStreaming && '▌'}
      </Text>
    </Box>
  );
});

interface UserQueryProps {
  query: string;
}

export function UserQuery({ query }: UserQueryProps) {
  return (
    <Box marginTop={1} paddingRight={2}>
      <Text color={colors.white} backgroundColor={colors.mutedDark}>
        {'>'} {query}{' '}
      </Text>
    </Box>
  );
}
