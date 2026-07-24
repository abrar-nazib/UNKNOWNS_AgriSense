import type { Message, ToolCall } from "./types";

function messageIndex(messages: Message[], messageId: number): number {
  return messages.findIndex((message) => message.id === messageId);
}

/**
 * Tool calls belong to a user turn, although the backend persists native
 * tool-call and final-answer AI messages separately for correct model replay.
 * Aggregate those adjacent assistant rows for display on the final reply.
 */
export function toolTraceForTurn(
  messages: Message[],
  assistantMessageId: number,
): ToolCall[] {
  const end = messageIndex(messages, assistantMessageId);
  if (end < 0 || messages[end].role !== "assistant") return [];

  let start = end;
  while (start > 0 && messages[start - 1].role !== "user") start -= 1;

  const calls: ToolCall[] = [];
  for (let index = start; index <= end; index += 1) {
    if (messages[index].role === "assistant") {
      calls.push(...messages[index].tool_trace);
    }
  }
  return calls;
}

export function isLastAssistantInTurn(
  messages: Message[],
  assistantMessageId: number,
): boolean {
  const index = messageIndex(messages, assistantMessageId);
  if (index < 0 || messages[index].role !== "assistant") return false;

  for (let next = index + 1; next < messages.length; next += 1) {
    if (messages[next].role === "user") break;
    if (messages[next].role === "assistant") return false;
  }
  return true;
}

/**
 * Derive a durable turn duration from persisted message timestamps. This keeps
 * the "Thought for …" label available after refresh without adding backend
 * fields or storing client-only timing state.
 */
export function turnDurationMs(
  messages: Message[],
  assistantMessageId: number,
): number | null {
  const end = messageIndex(messages, assistantMessageId);
  if (end < 0 || messages[end].role !== "assistant") return null;

  let promptIndex = end - 1;
  while (promptIndex >= 0 && messages[promptIndex].role !== "user") {
    promptIndex -= 1;
  }
  if (promptIndex < 0) return null;

  const startedAt = Date.parse(messages[promptIndex].created_at);
  const finishedAt = Date.parse(messages[end].created_at);
  const duration = finishedAt - startedAt;
  return Number.isFinite(duration) && duration >= 0 ? duration : null;
}

export function formatThoughtDuration(durationMs: number | null): string {
  if (durationMs == null) return "some time";
  if (durationMs < 1_000) return "less than a second";

  const seconds = Math.max(1, Math.round(durationMs / 1_000));
  if (seconds < 60) return `${seconds} ${seconds === 1 ? "second" : "seconds"}`;

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  const minuteLabel = `${minutes} ${minutes === 1 ? "min" : "mins"}`;
  return remainingSeconds === 0
    ? minuteLabel
    : `${minuteLabel} ${remainingSeconds} ${
        remainingSeconds === 1 ? "second" : "seconds"
      }`;
}

/**
 * Once the final answer exists, hide its preceding empty tool-only bubbles.
 * Their traces are rendered on the final answer instead.
 */
export function isSupersededToolStep(
  messages: Message[],
  assistantMessageId: number,
): boolean {
  const index = messageIndex(messages, assistantMessageId);
  const message = messages[index];
  if (
    !message ||
    message.role !== "assistant" ||
    message.content.trim() ||
    message.tool_trace.length === 0
  ) {
    return false;
  }

  for (let next = index + 1; next < messages.length; next += 1) {
    if (messages[next].role === "user") break;
    if (
      messages[next].role === "assistant" &&
      messages[next].content.trim()
    ) {
      return true;
    }
  }
  return false;
}
