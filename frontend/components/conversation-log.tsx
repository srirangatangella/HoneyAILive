"use client";

import type { ChatMessage } from "@/lib/types";

const timeFormatter = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function formatTimestamp(timestamp: string) {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return "--:--:--";
  }
  return timeFormatter.format(parsed);
}

export function ConversationLog({ messages }: { messages: ChatMessage[] }) {
  return (
    <div className="rounded-4xl border border-black/10 bg-white/70 p-5 shadow-panel backdrop-blur">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Conversation</h2>
        <span className="text-xs uppercase tracking-[0.24em] text-black/45">
          Live transcript
        </span>
      </div>
      <div className="max-h-[320px] space-y-3 overflow-y-auto pr-2">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`rounded-3xl px-4 py-3 ${
              message.role === "assistant"
                ? "bg-honey/15"
                : message.role === "user"
                  ? "bg-black/5"
                  : "bg-pine/10"
            }`}
          >
            <div className="mb-1 flex items-center justify-between gap-3 text-xs uppercase tracking-[0.22em] text-black/45">
              <span>{message.role}</span>
              <span className="tracking-[0.14em] text-black/35">{formatTimestamp(message.timestamp)}</span>
            </div>
            <p className="text-sm leading-6 text-black/85">{message.content}</p>
          </div>
        ))}
        {messages.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-black/10 px-4 py-6 text-sm text-black/55">
            Start a session, then say something like “Help me set up my router.”
          </div>
        ) : null}
      </div>
    </div>
  );
}
