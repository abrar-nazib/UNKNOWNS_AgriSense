import type { Message } from "./types";

/**
 * find-by-id replace or append. Used for both `message` and `message_update`
 * frames so the live buffer stays a single source of truth per bubble id.
 */
export function upsertMessage(list: Message[], msg: Message): Message[] {
  const idx = list.findIndex((m) => m.id === msg.id);
  if (idx === -1) return [...list, msg];
  const next = list.slice();
  next[idx] = msg;
  return next;
}

/**
 * Merge a fetched (persisted) list with any live-buffer messages, deduping by
 * id and preserving chronological order. Live SSE rows win on conflict: a
 * background fetch can contain the initial empty tool result while a later
 * `message_update` already carries the completed trace.
 */
export function mergeById(persisted: Message[], live: Message[]): Message[] {
  const byId = new Map(persisted.map((message) => [message.id, message]));
  for (const message of live) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}
