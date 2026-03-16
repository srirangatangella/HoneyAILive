"use client";

import { LoaderCircle, RefreshCw, MessageCircle } from "lucide-react";
import type { AssistantMode, TaskPlan } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TaskProgress({
  plan,
  assistantMode,
  onMarkStep,
  onRegenerate,
  isValidating = false,
}: {
  plan: TaskPlan | null;
  assistantMode: AssistantMode;
  onMarkStep: (stepId: string, status: "completed" | "blocked" | "in_progress") => void;
  onRegenerate?: () => void;
  isValidating?: boolean;
}) {
  const allDone = plan?.steps.every((s) => s.status === "completed") ?? false;

  return (
    <div className="rounded-4xl border border-black/10 bg-white/75 p-5 shadow-panel backdrop-blur">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Task progress</h2>
          <p className="text-sm text-black/55">
            {assistantMode === "general"
              ? "General mode focuses on observation and explanation instead of a repair checklist."
              : plan
                ? plan.goal
                : "No active DIY task yet."}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          {assistantMode === "diy" && plan && onRegenerate ? (
            <button
              onClick={onRegenerate}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-black/10 px-3 py-1.5 text-xs font-semibold text-black/60 transition hover:bg-black/5"
              title="Regenerate plan"
            >
              <RefreshCw size={14} />
              New plan
            </button>
          ) : null}
          {isValidating && (
            <div className="inline-flex items-center gap-1.5 rounded-full bg-honey/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-honey-dark animate-pulse">
              <LoaderCircle size={12} className="animate-spin" />
              AI Verifying...
            </div>
          )}
        </div>
      </div>
      <div className="space-y-3 overflow-hidden">
        {assistantMode === "general" ? (
          <div className="rounded-3xl border border-dashed border-black/10 px-4 py-6 text-sm text-black/55">
            Switch to DIY mode when you want HoneyAI to create a step-by-step repair or setup plan.
          </div>
        ) : null}
        {assistantMode === "diy" && plan?.steps.map((step, index) => (
          <div key={step.id} className="rounded-3xl border border-black/8 bg-black/[0.02] p-4">
            <div className="mb-2 flex items-start justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-[0.2em] text-black/45">
                  Step {index + 1}
                </div>
                <div className="font-semibold">{step.title}</div>
              </div>
              <span
                className={cn(
                  "rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]",
                  step.status === "completed" && "bg-pine text-white",
                  step.status === "in_progress" && "bg-honey text-black",
                  step.status === "blocked" && "bg-ember text-white",
                  step.status === "pending" && "bg-black/8 text-black/65"
                )}
              >
                {step.status.replace("_", " ")}
              </span>
            </div>
            <p className="text-sm leading-6 text-black/80">{step.instruction}</p>
            
            {step.last_validation_reasoning && step.status !== "completed" && (
              <div className="mt-3 flex items-start gap-2 rounded-2xl bg-white/50 p-3 text-xs italic text-black/60 shadow-sm border border-black/5">
                <MessageCircle size={14} className="mt-0.5 shrink-0" />
                <span>{step.last_validation_reasoning}</span>
              </div>
            )}

            {step.status !== "completed" && (
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => onMarkStep(step.id, "completed")}
                  className="rounded-full bg-pine px-3 py-2 text-xs font-semibold uppercase tracking-[0.15em] text-white transition hover:opacity-90"
                >
                  Mark done
                </button>
                <button
                  onClick={() => onMarkStep(step.id, "blocked")}
                  className="rounded-full border border-ember/20 bg-ember/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.15em] text-ember transition hover:bg-ember/15"
                >
                  Mark blocked
                </button>
              </div>
            )}
          </div>
        ))}
        {assistantMode === "diy" && plan && allDone ? (
          <div className="rounded-3xl border border-pine/20 bg-pine/5 px-4 py-6 text-center text-sm font-semibold text-pine">
            🎉 All steps completed! Great job.
          </div>
        ) : null}
        {assistantMode === "diy" && !plan ? (
          <div className="rounded-3xl border border-dashed border-black/10 px-4 py-6 text-sm text-black/55">
            Ask for setup or repair help and HoneyAI will generate a validated plan here.
          </div>
        ) : null}
      </div>
    </div>
  );
}
