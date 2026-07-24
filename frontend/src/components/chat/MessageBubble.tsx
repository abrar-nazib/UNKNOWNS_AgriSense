"use client";

import { Sprout } from "lucide-react";
import { memo } from "react";
import { PlanCard } from "@/components/plan/PlanCard";
import { planParse } from "@/lib/plan";
import type { Message, ProgressFrame } from "@/lib/types";
import { Markdown } from "./Markdown";
import { StatusPill } from "./StatusPill";

interface Props {
  message: Message;
  live?: boolean; // is this the currently-streaming turn?
  thinking?: ProgressFrame[]; // live turn only
  durationMs?: number | null; // completed turn, persisted timestamp delta
  activeTrace?: boolean; // panel currently showing this turn
  onToggleTrace?: (id: number) => void;
}

function MessageBubbleImpl({
  message,
  live,
  thinking,
  durationMs,
  activeTrace,
  onToggleTrace,
}: Props) {
  if (message.role === "user") {
    return (
      <div className="flex animate-fade-in justify-end">
        <div className="max-w-[75%] whitespace-pre-wrap rounded-[1.35rem] rounded-br-sm bg-field-700 px-4 py-2.5 text-paper-50 shadow-card">
          {message.content}
        </div>
      </div>
    );
  }

  const { plan, display } = planParse(message.content);
  const n = message.tool_trace.length;

  // Hide fully-empty intermediate tool steps that aren't the live turn.
  if (!display && !plan && n === 0 && !live) return null;

  return (
    <div className="flex animate-fade-in gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-jute-300/70 bg-paper-100 text-field-700 shadow-card">
        <Sprout size={18} strokeWidth={1.75} />
      </div>
      <div className="min-w-0 flex-1">
        {display && (
          <div className="animate-reveal">
            <Markdown content={display} />
          </div>
        )}
        {plan && <PlanCard plan={plan} />}
        <StatusPill
          live={!!live}
          calls={message.tool_trace}
          thinking={thinking}
          durationMs={durationMs}
          active={!!activeTrace}
          onClick={() => onToggleTrace?.(message.id)}
        />
        {message.model && <p className="mt-1.5 text-xs text-text-muted">{message.model}</p>}
      </div>
    </div>
  );
}

export const MessageBubble = memo(MessageBubbleImpl, (prev, next) => {
  const a = prev.message;
  const b = next.message;
  return (
    a.id === b.id &&
    a.content === b.content &&
    a.tool_trace === b.tool_trace &&
    a.model === b.model &&
    prev.live === next.live &&
    prev.durationMs === next.durationMs &&
    prev.activeTrace === next.activeTrace &&
    prev.thinking === next.thinking
  );
});
