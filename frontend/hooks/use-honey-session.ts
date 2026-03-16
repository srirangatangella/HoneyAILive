"use client";

import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { GoogleGenAI, MediaResolution, Modality, type LiveServerMessage } from "@google/genai";

import type { AssistantMode, ChatMessage, ConnectionStatus, TaskPlan } from "@/lib/types";
import { generateId } from "@/lib/utils";

const sessionStartTimeoutMs = 15000;
const reconnectDelayMs = 1000;

const GENERAL_SYSTEM_PROMPT =
  "You are HoneyAI in General mode. Answer directly about what the user shows. Use only the latest visible context for visual claims. If the image is unclear, say what is unclear instead of guessing. Respond with the final user-facing answer only.";

const DIY_SYSTEM_PROMPT =
  "You are HoneyAI in DIY mode. Observe carefully, speak like a calm human guide, and give the next safe step based on what is visible. Use only the latest visible context for visual claims. If the image is unclear, ask the user to reposition the camera. Respond with the final user-facing answer only.";

function base64ToUint8Array(base64: string) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function parseSampleRate(mimeType: string) {
  const match = mimeType.match(/rate=(\d+)/i);
  return match ? Number(match[1]) : 24000;
}

function resolveApiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configured) {
    return configured;
  }

  if (typeof window !== "undefined") {
    const { hostname, protocol } = window.location;
    // For local development, fallback to :8000
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      const localUrl = `${protocol}//${hostname}:8000`;
      console.log("[HoneyAI] Using local API URL:", localUrl);
      return localUrl;
    }
  }

  // In production, MUST have the env var. No more silent fallbacks to 'origin'.
  const finalUrl = configured || "MISSING_ENV_VAR_BACKEND_URL";
  if (typeof window !== "undefined") {
    console.log("[HoneyAI] Resolved API URL:", finalUrl);
  }
  return finalUrl;
}

function buildSystemPrompt(mode: AssistantMode) {
  return mode === "diy" ? DIY_SYSTEM_PROMPT : GENERAL_SYSTEM_PROMPT;
}

type LiveTokenResponse = {
  token: string;
  model: string;
  voiceName: string;
  expireTime?: string | null;
  newSessionExpireTime?: string | null;
};

export function useHoneySession() {
  const apiBaseUrl = useMemo(() => resolveApiBaseUrl(), []);
  const sessionRef = useRef<any>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackCursorRef = useRef(0);
  const sessionStartTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const resumeHandleRef = useRef<string | null>(null);
  const isIntentionalDisconnectRef = useRef(false);
  const pendingAssistantTranscriptRef = useRef("");
  const assistantModeRef = useRef<AssistantMode>("general");
  const currentTokenRef = useRef<LiveTokenResponse | null>(null);
  const planRef = useRef<TaskPlan | null>(null);

  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [plan, setPlan] = useState<TaskPlan | null>(null);
  const [sessionRuntime, setSessionRuntime] = useState<string>("disconnected");
  const [assistantMode, setAssistantMode] = useState<AssistantMode>("general");
  const [aiReadyForFrames, setAiReadyForFrames] = useState(false);
  const [isValidating, setIsValidating] = useState(false);

  useEffect(() => {
    assistantModeRef.current = assistantMode;
  }, [assistantMode]);

  useEffect(() => {
    planRef.current = plan;
  }, [plan]);

  useEffect(() => {
    return () => {
      clearSessionStartTimer();
      clearReconnectTimer();
      void closeSession(true);
      stopAudioPlayback();
    };
  }, []);

  function appendMessage(role: ChatMessage["role"], content: string) {
    startTransition(() => {
      setMessages((current) => [
        ...current,
        {
          id: generateId(),
          role,
          content,
          timestamp: new Date().toISOString(),
        },
      ]);
    });
  }

  function stopAudioPlayback() {
    playbackCursorRef.current = 0;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext) {
      audioContext.close().catch(() => undefined);
    }
  }

  function clearSessionStartTimer() {
    if (sessionStartTimerRef.current) {
      window.clearTimeout(sessionStartTimerRef.current);
      sessionStartTimerRef.current = null;
    }
  }

  function clearReconnectTimer() {
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }

  async function fetchLiveToken() {
    const response = await fetch(`${apiBaseUrl}/api/live/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Failed to create Gemini Live token.");
    }
    return (await response.json()) as LiveTokenResponse;
  }

  function buildLiveConfig(mode: AssistantMode, voiceName: string) {
    return {
      responseModalities: [Modality.AUDIO],
      systemInstruction: buildSystemPrompt(mode),
      inputAudioTranscription: {},
      outputAudioTranscription: {},
      mediaResolution: MediaResolution.MEDIA_RESOLUTION_LOW,
      speechConfig: {
        voiceConfig: {
          prebuiltVoiceConfig: {
            voiceName,
          },
        },
      },
      enableAffectiveDialog: true,
      sessionResumption: {
        handle: resumeHandleRef.current ?? undefined,
      },
      contextWindowCompression: {
        triggerTokens: "24000",
        slidingWindow: {
          targetTokens: "12000",
        },
      },
    };
  }

  async function createDirectSession(mode: AssistantMode, isReconnect: boolean) {
    clearSessionStartTimer();
    clearReconnectTimer();
    setStatus("connecting");
    setSessionRuntime("connecting");
    setAiReadyForFrames(false);
    pendingAssistantTranscriptRef.current = "";
    stopAudioPlayback();

    if (!isReconnect) {
      appendMessage("system", "Starting Gemini Live direct session...");
    }

    const tokenInfo = await fetchLiveToken();
    currentTokenRef.current = tokenInfo;

    const ai = new GoogleGenAI({
      apiKey: tokenInfo.token,
      httpOptions: { apiVersion: "v1alpha" },
    });

    sessionStartTimerRef.current = window.setTimeout(() => {
      appendMessage("system", "Gemini Live session start timed out. Please try again.");
      setStatus("error");
      void closeSession(true);
    }, sessionStartTimeoutMs);

    const session = await ai.live.connect({
      model: tokenInfo.model,
      config: buildLiveConfig(mode, tokenInfo.voiceName),
      callbacks: {
        onopen: () => {
          clearSessionStartTimer();
          setStatus("connected");
          setSessionRuntime("DirectGeminiLiveSession");
          setAiReadyForFrames(true);
          appendMessage("system", `Session started (DirectGeminiLiveSession, ${mode} mode).`);
        },
        onclose: () => {
          clearSessionStartTimer();
          sessionRef.current = null;
          setAiReadyForFrames(false);
          if (isIntentionalDisconnectRef.current) {
            setStatus("idle");
            setSessionRuntime("disconnected");
            return;
          }
          setStatus("error");
          appendMessage("system", "Gemini Live disconnected. Reconnecting...");
          reconnectTimerRef.current = window.setTimeout(() => {
            void createDirectSession(assistantModeRef.current, true).catch((error: unknown) => {
              const message = error instanceof Error ? error.message : "Gemini Live reconnect failed.";
              appendMessage("system", message);
              setStatus("error");
            });
          }, reconnectDelayMs);
        },
        onerror: (error: unknown) => {
          const message = error instanceof Error ? error.message : "Gemini Live error.";
          appendMessage("system", `Gemini Live error: ${message}`);
        },
        onmessage: async (message: LiveServerMessage) => {
          const resumption = message.sessionResumptionUpdate;
          if (resumption?.newHandle) {
            resumeHandleRef.current = resumption.newHandle;
          }

          const serverContent = message.serverContent;
          if (!serverContent) {
            return;
          }

          if (serverContent.interrupted) {
            stopAudioPlayback();
            pendingAssistantTranscriptRef.current = "";
          }

          if (serverContent.inputTranscription?.text) {
            const transcript = serverContent.inputTranscription.text;
            appendMessage("system", `Audio transcript: ${transcript}`);

            // Auto-generate a DIY plan from audio if none exists
            if (assistantModeRef.current === "diy" && !planRef.current) {
              void fetchDiyPlan(transcript);
            }
          }

          if (serverContent.outputTranscription?.text) {
            const chunk = serverContent.outputTranscription.text.trim();
            if (chunk) {
              pendingAssistantTranscriptRef.current = `${pendingAssistantTranscriptRef.current} ${chunk}`.trim();
            }
          }

          if (serverContent.modelTurn?.parts) {
            for (const part of serverContent.modelTurn.parts) {
              const inlineData = part.inlineData;
              if (!inlineData?.data) {
                continue;
              }
              setAiReadyForFrames(true);
              await playAudio(inlineData.data, inlineData.mimeType ?? "audio/pcm;rate=24000");
            }
          }

          if (serverContent.turnComplete) {
            const transcript = pendingAssistantTranscriptRef.current.trim();
            pendingAssistantTranscriptRef.current = "";
            setAiReadyForFrames(true);
            if (transcript) {
              appendMessage("assistant", transcript);
            }
          }
        },
      },
    });

    sessionRef.current = session;
  }

  async function closeSession(intentional: boolean) {
    isIntentionalDisconnectRef.current = intentional;
    clearSessionStartTimer();
    clearReconnectTimer();
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      try {
        await Promise.resolve(session.close());
      } catch {
        // Ignore close errors
      }
    }
  }

  function connect() {
    if (sessionRef.current || status === "connecting") {
      return;
    }
    isIntentionalDisconnectRef.current = false;
    void createDirectSession(assistantModeRef.current, false).catch((error: unknown) => {
      clearSessionStartTimer();
      const message = error instanceof Error ? error.message : "Failed to start Gemini Live.";
      appendMessage("system", message);
      setStatus("error");
      setSessionRuntime("disconnected");
      setAiReadyForFrames(false);
    });
  }

  function disconnect() {
    void closeSession(true);
    setStatus("idle");
    setSessionRuntime("disconnected");
    setAiReadyForFrames(false);
  }

  async function sendText(text: string, options?: { image?: string; mimeType?: string }) {
    if (!text.trim()) {
      return;
    }
    const session = sessionRef.current;
    if (!session) {
      appendMessage("system", "AI session is not started yet.");
      return;
    }

    stopAudioPlayback();
    appendMessage("user", text);

    // Auto-generate a DIY plan on the first text in DIY mode
    if (assistantModeRef.current === "diy" && !planRef.current) {
      void fetchDiyPlan(text);
    }

    const parts: Array<Record<string, unknown>> = [{ text }];
    if (options?.image) {
      parts.push({
        inlineData: {
          mimeType: options.mimeType ?? "image/jpeg",
          data: options.image,
        },
      });
    }

    await session.sendClientContent({
      turns: {
        role: "user",
        parts,
      },
      turnComplete: true,
    });
  }

  function updateAssistantMode(mode: AssistantMode) {
    setAssistantMode(mode);
    setPlan(null);
    if (status === "connected") {
      void closeSession(true).finally(() => {
        isIntentionalDisconnectRef.current = false;
        void createDirectSession(mode, false).catch((error: unknown) => {
          const message = error instanceof Error ? error.message : "Failed to switch Gemini Live mode.";
          appendMessage("system", message);
          setStatus("error");
        });
      });
    }
  }

  async function fetchDiyPlan(goal: string) {
    appendMessage("system", "HoneyAI is generating your repair plan...");
    try {
      const response = await fetch(`${apiBaseUrl}/api/diy/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });
      if (!response.ok) {
        appendMessage("system", "Failed to reach the planning agent. Please check your backend.");
        return;
      }
      const data = await response.json();
      if (data?.steps?.length) {
        setPlan(data as TaskPlan);
        appendMessage("system", `Formulated plan for: ${data.goal}`);
      } else {
        appendMessage("system", "Planning agent returned an empty plan. Try a different query.");
      }
    } catch (err) {
      console.error("fetchDiyPlan error:", err);
      appendMessage("system", "Critical error fetching DIY plan. Check console and backend logs.");
    }
  }

  function regeneratePlan(goal?: string) {
    const planGoal = goal ?? plan?.goal;
    if (planGoal) {
      setPlan(null);
      void fetchDiyPlan(planGoal);
    }
  }

  function updateStep(stepId: string, newStatus: "completed" | "blocked" | "in_progress", reasoning?: string) {
    setPlan((currentPlan) => {
      if (!currentPlan) return null;
      const updatedSteps = currentPlan.steps.map((step, index) => {
        if (step.id !== stepId) return step;
        const updated = { ...step, status: newStatus, last_validation_reasoning: reasoning ?? step.last_validation_reasoning };
        return updated;
      });

      // Auto-advance: find the completed step and mark next as in_progress
      if (newStatus === "completed") {
        const completedIndex = updatedSteps.findIndex((s) => s.id === stepId);
        if (completedIndex >= 0 && completedIndex + 1 < updatedSteps.length) {
          const next = updatedSteps[completedIndex + 1];
          if (next.status === "pending") {
            updatedSteps[completedIndex + 1] = { ...next, status: "in_progress" };
          }
        }
      }

      const nextCurrent = updatedSteps.find((s) => s.status === "in_progress");
      return {
        ...currentPlan,
        steps: updatedSteps,
        current_step_id: nextCurrent?.id ?? currentPlan.current_step_id,
      };
    });
  }

  async function validateCurrentStep(base64Image: string, mimeType: string) {
    if (!plan || assistantMode !== "diy" || isValidating) return;

    const currentStep = plan.steps.find((s) => s.id === plan.current_step_id);
    if (!currentStep || currentStep.status !== "in_progress") return;

    setIsValidating(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/diy/validate-step`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image: base64Image,
          mimeType: mimeType,
          step: currentStep,
        }),
      });

      if (response.ok) {
        const result = await response.json();
        // Always update the reasoning even if status is in_progress
        updateStep(currentStep.id, result.status, result.reasoning);
      }
    } catch (err) {
      console.error("Auto-validation failed:", err);
    } finally {
      setIsValidating(false);
    }
  }

  async function playAudio(base64Audio: string, mimeType: string) {
    const audioContext = audioContextRef.current ?? new AudioContext({ sampleRate: parseSampleRate(mimeType) });
    audioContextRef.current = audioContext;
    if (audioContext.state === "suspended") {
      await audioContext.resume();
    }

    if (mimeType.includes("pcm")) {
      const sampleRate = parseSampleRate(mimeType);
      const bytes = base64ToUint8Array(base64Audio);
      const pcm16 = new Int16Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
      const float32 = new Float32Array(pcm16.length);
      for (let index = 0; index < pcm16.length; index += 1) {
        float32[index] = pcm16[index] / 32768;
      }

      const audioBuffer = audioContext.createBuffer(1, float32.length, sampleRate);
      audioBuffer.copyToChannel(float32, 0);
      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);
      const startAt = Math.max(audioContext.currentTime, playbackCursorRef.current);
      source.start(startAt);
      playbackCursorRef.current = startAt + audioBuffer.duration;
      return;
    }

    const audio = new Audio(`data:${mimeType};base64,${base64Audio}`);
    await audio.play().catch(() => undefined);
  }

  function sendVideoFrame(base64Image: string, mimeType = "image/jpeg") {
    const session = sessionRef.current;
    if (!session) {
      return;
    }
    try {
      session.sendRealtimeInput({
        video: {
          data: base64Image,
          mimeType,
        },
      });
    } catch {
      // Silently ignore — frame drops are acceptable for continuous streaming
    }
  }

  function sendRealtimeAudio(base64Pcm: string) {
    const session = sessionRef.current;
    if (!session) {
      return;
    }
    try {
      session.sendRealtimeInput({
        audio: {
          data: base64Pcm,
          mimeType: "audio/pcm;rate=16000",
        },
      });
    } catch {
      // Silently ignore — audio drops are acceptable for continuous streaming
    }
  }

  return {
    status,
    connected: status === "connected",
    messages,
    plan,
    sessionRuntime,
    assistantMode,
    aiReadyForFrames,
    isValidating,
    connect,
    disconnect,
    sendText,
    sendVideoFrame,
    sendRealtimeAudio,
    updateAssistantMode,
    updateStep,
    validateCurrentStep,
    regeneratePlan,
  };
}
