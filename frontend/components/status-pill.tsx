"use client";

import { cn } from "@/lib/utils";

export function StatusPill({
  label,
  tone,
}: {
  label: string;
  tone: "neutral" | "success" | "warning";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em]",
        tone === "success" && "bg-pine/10 text-pine",
        tone === "warning" && "bg-ember/10 text-ember",
        tone === "neutral" && "bg-black/5 text-black/70"
      )}
    >
      {label}
    </span>
  );
}
