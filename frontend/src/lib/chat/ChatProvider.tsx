"use client";

// App-level chat state so a stream KEEPS RUNNING across navigation (#1). The
// provider is mounted above the router, so leaving /chat unmounts only the UI —
// the in-flight stream continues here and is still there when you return.

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { qk, useMessages } from "@/lib/hooks";
import { streamChat } from "@/lib/stream";
import { getAccess, getStoredSessionId, setStoredSessionId } from "@/lib/tokens";
import type { Message, ProgressFrame } from "@/lib/types";
import { mergeById, upsertMessage } from "@/lib/upsert";

interface ChatCtx {
  sessionId: number | null;
  messages: Message[];
  streaming: boolean;
  thinking: ProgressFrame[];
  streamingTurnId: number | null; // assistant message id of the live turn
  error: string | null;
  send: (message: string) => Promise<void>;
  stop: () => void;
  newChat: () => void;
  selectSession: (id: number) => void;
}

const Ctx = createContext<ChatCtx | null>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const selfCreatedRef = useRef<number | null>(null);

  const [sessionId, setSessionId] = useState<number | null>(null);
  const [live, setLive] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [thinking, setThinking] = useState<ProgressFrame[]>([]);
  const [streamingTurnId, setStreamingTurnId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Restore the last active session once, if signed in.
  useEffect(() => {
    if (getAccess()) {
      const s = getStoredSessionId();
      if (s != null) setSessionId(s);
    }
  }, []);

  const { data: persisted } = useMessages(sessionId);
  const messages = useMemo(() => mergeById(persisted ?? [], live), [persisted, live]);

  const send = useCallback(
    async (message: string) => {
      if (streaming) return;
      setError(null);
      setThinking([]);
      setStreamingTurnId(null);
      setStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;
      let turnSessionId = sessionId;

      await streamChat({
        message,
        sessionId,
        signal: controller.signal,
        onEvent: (frame) => {
          switch (frame.type) {
            case "session":
              if (turnSessionId == null) {
                turnSessionId = frame.session_id;
                selfCreatedRef.current = frame.session_id;
                setStoredSessionId(frame.session_id);
                setSessionId(frame.session_id);
              }
              break;
            case "message":
            case "message_update":
              if (frame.message.role === "assistant") setStreamingTurnId(frame.message.id);
              setLive((prev) => upsertMessage(prev, frame.message));
              if (turnSessionId != null) {
                qc.setQueryData<Message[]>(
                  qk.messages(turnSessionId),
                  (previous = []) => upsertMessage(previous, frame.message),
                );
              }
              break;
            case "progress":
              setThinking((t) => [...t, frame]);
              break;
            case "error":
              setError(frame.detail);
              break;
            case "done":
              break;
          }
        },
      });

      setStreaming(false);
      const fin = turnSessionId;
      if (fin != null) {
        await qc.invalidateQueries({ queryKey: qk.messages(fin) });
        await qc.invalidateQueries({ queryKey: qk.sessions });
      }
      setLive([]);
      setStreamingTurnId(null);
      selfCreatedRef.current = null;
    },
    [sessionId, streaming, qc],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
    setStreamingTurnId(null);
  }, []);

  const resetStream = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setLive([]);
    setThinking([]);
    setStreaming(false);
    setStreamingTurnId(null);
    setError(null);
  };

  const newChat = useCallback(() => {
    resetStream();
    setSessionId(null);
    setStoredSessionId(null);
  }, []);

  const selectSession = useCallback(
    (id: number) => {
      if (id === sessionId) return;
      if (id === selfCreatedRef.current) {
        setSessionId(id); // our own in-flight stream just created this — keep it
        return;
      }
      resetStream();
      setSessionId(id);
      setStoredSessionId(id);
    },
    [sessionId],
  );

  const value = useMemo<ChatCtx>(
    () => ({
      sessionId,
      messages,
      streaming,
      thinking,
      streamingTurnId,
      error,
      send,
      stop,
      newChat,
      selectSession,
    }),
    [sessionId, messages, streaming, thinking, streamingTurnId, error, send, stop, newChat, selectSession],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChat(): ChatCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useChat must be used within <ChatProvider>");
  return c;
}
