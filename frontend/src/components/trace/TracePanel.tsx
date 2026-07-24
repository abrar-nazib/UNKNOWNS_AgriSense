"use client";

// Single-prompt trace panel (#4). Shows the trace of ONE prompt only — the one whose
// status pill was clicked, or the live streaming turn. No history of other prompts.
// Right side, collapsible (the pill and the panel's own button both toggle it).

import {
  Activity,
  Brain,
  Check,
  ChevronRight,
  Copy,
  PanelRightClose,
  PanelRightOpen,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { formatThoughtDuration } from "@/lib/chatTurns";
import type { ProgressFrame, ToolCall } from "@/lib/types";

// Pretty-print a raw tool result: JSON if parseable, otherwise the raw string.
function prettyResult(s: string): string {
  const t = s.trim();
  if (!t) return "—";
  try {
    return JSON.stringify(JSON.parse(t), null, 2);
  } catch {
    return s;
  }
}

function summarizeArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => {
      const s = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}: ${s.length > 22 ? s.slice(0, 22) + "…" : s}`;
    })
    .join(", ");
}

function ToolCallRow({ call, newest }: { call: ToolCall; newest: boolean }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(call.result || "").then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <div
      className={`animate-stream-in rounded-lg border bg-panel-2 ${
        newest ? "border-signal/60 animate-glow-pulse" : "border-hairline"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
      >
        <Wrench size={13} strokeWidth={2} className="shrink-0 text-signal" />
        <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink">
          {call.tool}
          <span className="text-ink-dim">({summarizeArgs(call.args)})</span>
        </span>
        <ChevronRight
          size={13}
          className={`shrink-0 text-ink-dim transition-transform ${open ? "rotate-90" : ""}`}
        />
      </button>
      {open && (
        <div className="space-y-2 border-t border-hairline px-2.5 py-2">
          <div>
            <p className="mb-1 font-mono text-[10px] uppercase tracking-wide text-ink-dim">params sent</p>
            <pre className="nums overflow-x-auto rounded bg-panel p-2 font-mono text-xs text-ink">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between">
              <p className="font-mono text-[10px] uppercase tracking-wide text-ink-dim">raw result</p>
              {call.result && (
                <button
                  type="button"
                  onClick={copy}
                  aria-label="Copy raw result"
                  className="flex items-center gap-1 font-mono text-[10px] text-ink-dim transition hover:text-signal"
                >
                  {copied ? <Check size={11} /> : <Copy size={11} />}
                  {copied ? "copied" : "copy"}
                </button>
              )}
            </div>
            <pre className="nums max-h-40 overflow-auto rounded bg-panel p-2 font-mono text-xs text-signal-deep">
              {prettyResult(call.result)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function ThinkingTimeline({ thinking, streaming }: { thinking: ProgressFrame[]; streaming: boolean }) {
  if (thinking.length === 0) return null;
  return (
    <section>
      <p className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-ink-dim">
        <Activity size={12} /> Thinking
      </p>
      <ol className="space-y-1.5 border-l border-hairline pl-3">
        {thinking.map((t, i) => {
          const last = i === thinking.length - 1;
          return (
            <li key={i} className="relative">
              <span
                className={`absolute -left-[15px] top-1 h-1.5 w-1.5 rounded-full ${
                  last && streaming ? "animate-pulse-dot bg-signal" : "bg-signal/50"
                }`}
              />
              <span className="font-mono text-xs leading-snug text-ink">
                <span className="text-ink-dim">{t.stage}:</span> {t.detail}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export interface FocusedTurn {
  id: number;
  prompt: string;
  calls: ToolCall[];
  durationMs: number | null;
}

interface Props {
  turn: FocusedTurn | null;
  thinking: ProgressFrame[]; // shown only when isLive
  isLive: boolean;
  model?: string;
  collapsed: boolean;
  onToggle: () => void;
}

export function TracePanel({ turn, thinking, isLive, model, collapsed, onToggle }: Props) {
  const count = turn?.calls.length ?? 0;

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        aria-label="Show agent trace"
        className="relative flex h-full w-11 shrink-0 flex-col items-center gap-2 border-l border-jute-300/55 bg-paper-100 py-4 text-ink-dim transition hover:bg-paper-50 hover:text-signal hover:shadow-lift"
      >
        <PanelRightOpen size={18} />
        {count > 0 && (
          <span className="nums absolute right-1.5 top-1.5 rounded-full bg-signal px-1.5 text-[10px] font-semibold text-canvas">
            {count}
          </span>
        )}
        <span className="[writing-mode:vertical-rl] font-mono text-xs tracking-widest">
          AGENT TRACE
        </span>
      </button>
    );
  }

  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex h-full w-[min(340px,calc(100vw-3.5rem))] shrink-0 flex-col border-l border-jute-300/55 bg-paper-100 shadow-[-18px_0_45px_-30px_rgba(23,53,27,.5)] sm:relative sm:z-auto sm:w-[340px]">
      <div className="flex items-center justify-between border-b border-hairline px-3 py-3">
        <span className="min-w-0">
          <span className="block font-mono text-xs uppercase tracking-widest text-ink-dim">
            Agent Trace{count > 0 ? ` · ${count}` : ""}
          </span>
          {model && <span className="block truncate font-mono text-[10px] text-signal">{model}</span>}
        </span>
        <button
          type="button"
          onClick={onToggle}
          aria-label="Hide agent trace"
          className="shrink-0 text-ink-dim transition hover:text-ink"
        >
          <PanelRightClose size={16} />
        </button>
      </div>

      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-3">
        {!turn ? (
          isLive && thinking.length > 0 ? (
            <ThinkingTimeline thinking={thinking} streaming />
          ) : (
            <p className="px-1 py-4 font-mono text-xs text-ink-dim">
              Click a prompt&apos;s status (e.g. “thinking finished · 2 tools”) to see its trace here.
            </p>
          )
        ) : (
          <>
            {turn.prompt && (
              <p className="rounded-lg border border-hairline bg-panel-2 px-2.5 py-2 text-xs italic text-ink">
                “{turn.prompt.length > 90 ? turn.prompt.slice(0, 90) + "…" : turn.prompt}”
              </p>
            )}

            {isLive && <ThinkingTimeline thinking={thinking} streaming={isLive} />}

            {!isLive && (
              <p className="flex items-center gap-2 rounded-lg border border-hairline bg-panel-2 px-2.5 py-2 font-mono text-xs text-ink">
                <Brain size={13} className="shrink-0 text-signal" />
                Thought for {formatThoughtDuration(turn.durationMs)}
              </p>
            )}

            {turn.calls.length === 0 ? (
              <p className="px-1 font-mono text-xs text-ink-dim">
                {isLive ? "No tools called yet for this prompt." : "This prompt used no tools."}
              </p>
            ) : (
              <section>
                <p className="mb-1.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-signal">
                  <Wrench size={12} /> Tool calls
                </p>
                <div className="space-y-1.5">
                  {turn.calls.map((c, i) => (
                    <ToolCallRow
                      key={`${turn.id}-${i}`}
                      call={c}
                      newest={isLive && i === turn.calls.length - 1 && !c.result}
                    />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
