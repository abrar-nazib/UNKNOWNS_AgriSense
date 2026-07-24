"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Sprout, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { TracePanel, type FocusedTurn } from "@/components/trace/TracePanel";
import { useChat } from "@/lib/chat/ChatProvider";
import {
  isLastAssistantInTurn,
  isSupersededToolStep,
  toolTraceForTurn,
  turnDurationMs,
} from "@/lib/chatTurns";
import { qk } from "@/lib/hooks";
import type { Message } from "@/lib/types";
import { Composer, type ComposerHandle } from "./Composer";
import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";
import { StatusPill } from "./StatusPill";

function promptFor(messages: Message[], turnId: number): string {
  const idx = messages.findIndex((m) => m.id === turnId);
  for (let j = idx - 1; j >= 0; j--) {
    if (messages[j].role === "user") return messages[j].content;
  }
  return "";
}

export function ChatColumn() {
  const { sessionId, messages, streaming, thinking, streamingTurnId, error, send, stop } = useChat();
  const qc = useQueryClient();
  const composerRef = useRef<ComposerHandle>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [traceOpen, setTraceOpen] = useState(false);
  const [focusedTurnId, setFocusedTurnId] = useState<number | null>(null);

  // On return to /chat (this component re-mounts), force a fresh fetch — the stream
  // keeps running in ChatProvider while you're away, so the reply may have landed.
  useEffect(() => {
    if (sessionId != null) qc.invalidateQueries({ queryKey: qk.messages(sessionId) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset the panel when the session changes.
  useEffect(() => {
    setTraceOpen(false);
    setFocusedTurnId(null);
  }, [sessionId]);

  // The panel follows the live streaming turn.
  useEffect(() => {
    if (streamingTurnId != null) setFocusedTurnId(streamingTurnId);
  }, [streamingTurnId]);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, thinking, streaming]);

  const toggleTrace = (turnId: number | null) => {
    if (traceOpen && focusedTurnId === turnId) setTraceOpen(false);
    else {
      setFocusedTurnId(turnId);
      setTraceOpen(true);
    }
  };

  const focusedMsg =
    focusedTurnId != null ? messages.find((m) => m.id === focusedTurnId) : undefined;
  const isLive = streaming && (focusedTurnId == null || focusedTurnId === streamingTurnId);
  const focusedTurn: FocusedTurn | null = focusedMsg
    ? {
        id: focusedMsg.id,
        prompt: promptFor(messages, focusedMsg.id),
        calls: toolTraceForTurn(messages, focusedMsg.id),
        durationMs: turnDurationMs(messages, focusedMsg.id),
      }
    : null;
  const model = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].model) return messages[i].model;
    }
    return "";
  }, [messages]);

  const handlePick = (p: string) => composerRef.current?.setValue(p);
  const showEmpty = messages.length === 0 && !streaming;
  const hasLiveBubble = streamingTurnId != null;

  return (
    <div className="relative flex h-full flex-1 overflow-hidden bg-background">
      <div className="flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="chat-bg flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col">
            {showEmpty ? (
              <EmptyState onPick={handlePick} />
            ) : (
              <div className="flex flex-col gap-5 px-4 py-6">
                {messages.map((m) => {
                  if (isSupersededToolStep(messages, m.id)) return null;
                  const calls =
                    m.role === "assistant" &&
                    isLastAssistantInTurn(messages, m.id)
                      ? toolTraceForTurn(messages, m.id)
                      : m.tool_trace;
                  const displayMessage =
                    calls === m.tool_trace ? m : { ...m, tool_trace: calls };
                  return (
                    <MessageBubble
                      key={m.id}
                      message={displayMessage}
                      live={streaming && m.id === streamingTurnId}
                      thinking={
                        m.id === streamingTurnId ? thinking : undefined
                      }
                      durationMs={
                        m.role === "assistant" &&
                        isLastAssistantInTurn(messages, m.id)
                          ? turnDurationMs(messages, m.id)
                          : null
                      }
                      activeTrace={traceOpen && focusedTurnId === m.id}
                      onToggleTrace={toggleTrace}
                    />
                  );
                })}
                {/* Live pill before the assistant bubble exists (initial thinking). */}
                {streaming && !hasLiveBubble && (
                  <div className="flex animate-fade-in gap-3">
                    <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-100 text-primary-600">
                      <Sprout size={18} strokeWidth={1.75} />
                    </div>
                    <div>
                      <StatusPill
                        live
                        calls={[]}
                        thinking={thinking}
                        active={traceOpen && focusedTurnId == null}
                        onClick={() => toggleTrace(null)}
                      />
                    </div>
                  </div>
                )}
                {error && (
                  <div className="rounded-lg border border-status-error bg-status-error-chip px-4 py-3 text-sm text-status-error">
                    {error}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {streaming && (
          <div className="flex justify-center pb-1">
            <button
              type="button"
              onClick={stop}
              className="flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-text-primary shadow-card transition hover:border-status-error hover:text-status-error"
            >
              <Square size={11} fill="currentColor" /> Stop
            </button>
          </div>
        )}

        <Composer ref={composerRef} onSend={send} disabled={streaming} />
      </div>

      <TracePanel
        turn={focusedTurn}
        thinking={isLive ? thinking : []}
        isLive={isLive}
        model={model}
        collapsed={!traceOpen}
        onToggle={() => setTraceOpen((o) => !o)}
      />
    </div>
  );
}
