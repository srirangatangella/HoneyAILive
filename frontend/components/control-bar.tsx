"use client";

import { Camera, LoaderCircle, Mic, MonitorUp, PhoneCall, PhoneOff, Send, Wrench } from "lucide-react";

import type { AssistantMode, ConnectionStatus } from "@/lib/types";

type Props = {
  status: ConnectionStatus;
  connected: boolean;
  cameraEnabled: boolean;
  listening: boolean;
  screenShareEnabled: boolean;
  speechSupported: boolean;
  assistantMode: AssistantMode;
  onStart: () => void;
  onStop: () => void;
  onToggleCamera: () => void;
  onToggleScreenShare: () => void;
  onModeChange: (mode: AssistantMode) => void;
  onTalkStart: () => void;
  onTalkStop: () => void;
  prompt: string;
  onPromptChange: (value: string) => void;
  onSend: () => void;
};

export function ControlBar({
  status,
  connected,
  cameraEnabled,
  listening,
  screenShareEnabled,
  speechSupported,
  assistantMode,
  onStart,
  onStop,
  onToggleCamera,
  onToggleScreenShare,
  onModeChange,
  onTalkStart,
  onTalkStop,
  prompt,
  onPromptChange,
  onSend,
}: Props) {
  const starting = status === "connecting";

  return (
    <div className="rounded-4xl border border-black/10 bg-white/75 p-5 shadow-panel backdrop-blur">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={starting}
          onClick={connected ? onStop : onStart}
          className={`inline-flex items-center gap-2 rounded-full px-4 py-3 text-sm font-semibold transition ${
            connected
              ? "bg-black text-white hover:bg-black/85"
              : starting
                ? "bg-black/10 text-black/60"
                : "bg-honey text-black hover:bg-honey/85"
          } disabled:cursor-wait disabled:opacity-90`}
        >
          {connected ? <PhoneOff size={18} /> : starting ? <LoaderCircle size={18} className="animate-spin" /> : <PhoneCall size={18} />}
          {connected ? "Stop AI" : starting ? "Starting AI..." : "Start AI"}
        </button>
        <button
          onClick={onToggleCamera}
          className={`inline-flex items-center gap-2 rounded-full border px-4 py-3 text-sm font-semibold transition ${
            cameraEnabled
              ? "border-pine/15 bg-pine/10 text-pine"
              : "border-black/10 bg-white text-black/70"
          }`}
        >
          <Camera size={18} />
          Toggle camera
        </button>
        <button
          onClick={onToggleScreenShare}
          className={`inline-flex items-center gap-2 rounded-full border px-4 py-3 text-sm font-semibold transition ${
            screenShareEnabled
              ? "border-honey/20 bg-honey/15 text-black"
              : "border-black/10 bg-white text-black/70 hover:bg-black/5"
          }`}
        >
          <MonitorUp size={18} />
          Toggle screen share
        </button>
        <button
          onMouseDown={assistantMode !== "diy" ? onTalkStart : undefined}
          onMouseUp={assistantMode !== "diy" ? onTalkStop : undefined}
          onMouseLeave={assistantMode !== "diy" ? onTalkStop : undefined}
          onTouchStart={assistantMode !== "diy" ? onTalkStart : undefined}
          onTouchEnd={assistantMode !== "diy" ? onTalkStop : undefined}
          disabled={!connected || !speechSupported}
          className={`inline-flex items-center gap-2 rounded-full px-4 py-3 text-sm font-semibold transition ${
            assistantMode === "diy" && connected
              ? "bg-pine text-white animate-[pulse_2s_ease-in-out_infinite]"
              : listening
                ? "bg-ember text-white shadow-[0_0_20px_rgba(255,87,51,0.4)]"
                : "border border-black/10 bg-white text-black/70 hover:bg-black/5"
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          <Mic size={18} />
          {assistantMode === "diy" && connected
            ? "Active listening..."
            : speechSupported
              ? listening
                ? "Release to send"
                : "Hold to talk"
              : "Speech unsupported"}
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-3">
        <button
          onClick={() => onModeChange("general")}
          className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
            assistantMode === "general"
              ? "bg-black text-white"
              : "border border-black/10 bg-white text-black/70 hover:bg-black/5"
          }`}
        >
          General mode
        </button>
        <button
          onClick={() => onModeChange("diy")}
          className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition ${
            assistantMode === "diy"
              ? "bg-pine text-white"
              : "border border-black/10 bg-white text-black/70 hover:bg-black/5"
          }`}
        >
          <Wrench size={16} />
          DIY mode
        </button>
      </div>

      <div className="flex flex-col gap-3 md:flex-row">
        <input
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          placeholder={assistantMode === "diy" ? "Ask for setup or repair help." : "Ask what HoneyAI sees or explain the scene."}
          className="min-w-0 flex-1 rounded-full border border-black/10 bg-white px-5 py-3 text-sm outline-none transition focus:border-honey"
        />
        <button
          onClick={onSend}
          className="inline-flex items-center justify-center gap-2 rounded-full bg-pine px-5 py-3 text-sm font-semibold text-white transition hover:opacity-90"
        >
          <Send size={18} />
          Send
        </button>
      </div>
    </div>
  );
}
