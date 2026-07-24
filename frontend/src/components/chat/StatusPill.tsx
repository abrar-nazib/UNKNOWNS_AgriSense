"use client";

// The ONE clickable per prompt (#4). While the turn streams, its label tracks the
// live status (thinking… → calling <tool>… → tool called → thinking finished). When
// done it stays as a single "thinking finished · N tools" affordance. Clicking it
// toggles the trace panel for THIS prompt only.

import { Brain, ChevronRight, Loader2 } from "lucide-react";
import { formatThoughtDuration } from "@/lib/chatTurns";
import type { ProgressFrame, ToolCall } from "@/lib/types";

interface Props {
  live: boolean; // is this the currently-streaming turn?
  calls: ToolCall[];
  thinking?: ProgressFrame[]; // live turn's step frames (for the label)
  durationMs?: number | null; // completed turn, derived from persisted timestamps
  active: boolean; // panel is currently showing this turn
  onClick: () => void;
}

function liveLabel(calls: ToolCall[], thinking?: ProgressFrame[]): string {
  const pending = calls.find((c) => !c.result);
  if (pending) return `calling ${pending.tool}…`;
  if (calls.length > 0) return `tool called: ${calls[calls.length - 1].tool}`;
  const last = thinking?.[thinking.length - 1];
  if (last?.stage === "tool") return last.detail || "using a tool…";
  if (last?.stage === "memory") return last.detail || "recalling memory…";
  return "thinking…";
}

export function StatusPill({
  live,
  calls,
  thinking,
  durationMs = null,
  active,
  onClick,
}: Props) {
  const label = live
    ? liveLabel(calls, thinking)
    : `Thought for ${formatThoughtDuration(durationMs)}${
        calls.length
          ? ` · ${calls.length} tool${calls.length > 1 ? "s" : ""}`
          : " · no tools"
      }`;

  return (
    <button
      type="button"
      onClick={onClick}
      title="Toggle this prompt's agent trace"
      className={`mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition duration-200 hover:-translate-y-0.5 hover:shadow-card ${
        active
          ? "border-signal/50 bg-signal/10 text-signal"
          : "border-border bg-surface text-text-muted hover:border-primary-300 hover:text-primary-700"
      }`}
    >
      {live ? (
        <Loader2 size={12} className="shrink-0 animate-spin text-primary-600" />
      ) : (
        <Brain size={12} className="shrink-0 text-primary-600" />
      )}
      <span className="truncate">{label}</span>
      <ChevronRight size={12} className="shrink-0" />
    </button>
  );
}
