"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Camera, Mic, ShieldCheck } from "lucide-react";

import { ControlBar } from "@/components/control-bar";
import { ConversationLog } from "@/components/conversation-log";
import { StatusPill } from "@/components/status-pill";
import { TaskProgress } from "@/components/task-progress";
import { useHoneySession } from "@/hooks/use-honey-session";
import { arrayBufferToBase64, pcmAudioWorkletCode } from "@/lib/audio-processor";
import type { AssistantMode } from "@/lib/types";

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
  }
}

type SpeechRecognitionAlternative = {
  transcript: string;
};

type SpeechRecognitionResultLike = {
  isFinal: boolean;
  0: SpeechRecognitionAlternative;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
};

type SpeechRecognitionInstance = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  start: () => void;
  stop: () => void;
};

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Failed to convert blob to base64"));
        return;
      }
      resolve(result.split(",")[1] ?? "");
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return target.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export default function HomePage() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);
  const spokenTextRef = useRef("");
  const lastFrameCapturedAtRef = useRef(0);
  const pushToTalkKeyActiveRef = useRef(false);

  const [cameraEnabled, setCameraEnabled] = useState(false);
  const [screenShareEnabled, setScreenShareEnabled] = useState(false);
  const [listening, setListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [prompt, setPrompt] = useState("");

  const {
    connected,
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
    status,
    updateAssistantMode,
    updateStep,
    validateCurrentStep,
    regeneratePlan,
  } = useHoneySession();

  const sendTextRef = useRef(sendText);
  const captureFrameRef = useRef(captureCurrentFrame);
  const sendAudioRef = useRef(sendRealtimeAudio);

  const audioContextRef = useRef<AudioContext | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const audioWorkletNodeRef = useRef<AudioWorkletNode | null>(null);

  const visualInputEnabled = cameraEnabled || screenShareEnabled;

  // Keep refs in sync so the stable recognition callback uses the latest versions
  useEffect(() => {
    sendTextRef.current = sendText;
    captureFrameRef.current = captureCurrentFrame;
    sendAudioRef.current = sendRealtimeAudio;
  });

  // ── Continuous video frame streaming at ~1fps ──────────────────────────
  useEffect(() => {
    if (!connected || !visualInputEnabled || !aiReadyForFrames) {
      return;
    }

    const intervalId = window.setInterval(async () => {
      const frame = await captureCurrentFrame(false);
      if (frame) {
        sendVideoFrame(frame.image, frame.mimeType);
      }
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [connected, visualInputEnabled, aiReadyForFrames, sendVideoFrame]);

  // ── Continuous audio streaming for DIY mode ──────────────────────────────
  useEffect(() => {
    if (!connected || assistantMode !== "diy") {
      if (audioContextRef.current) {
        void audioContextRef.current.close();
        audioContextRef.current = null;
      }
      if (audioStreamRef.current) {
        audioStreamRef.current.getTracks().forEach((track) => track.stop());
        audioStreamRef.current = null;
      }
      return;
    }

    let isSubscribed = true;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!isSubscribed) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        audioStreamRef.current = stream;

        const audioCtx = new AudioContext({ sampleRate: 16000 });
        audioContextRef.current = audioCtx;

        const blob = new Blob([pcmAudioWorkletCode], { type: "application/javascript" });
        const workletUrl = URL.createObjectURL(blob);
        await audioCtx.audioWorklet.addModule(workletUrl);
        URL.revokeObjectURL(workletUrl);

        if (!isSubscribed) return;

        const source = audioCtx.createMediaStreamSource(stream);
        const workletNode = new AudioWorkletNode(audioCtx, "pcm-processor");
        audioWorkletNodeRef.current = workletNode;

        workletNode.port.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            const base64 = arrayBufferToBase64(event.data);
            sendAudioRef.current(base64);
          }
        };

        source.connect(workletNode);
        workletNode.connect(audioCtx.destination);
      } catch (err) {
        console.error("Failed to start continuous audio streaming:", err);
      }
    })();

    return () => {
      isSubscribed = false;
      if (audioContextRef.current) {
        void audioContextRef.current.close();
        audioContextRef.current = null;
      }
      if (audioStreamRef.current) {
        audioStreamRef.current.getTracks().forEach((t) => t.stop());
        audioStreamRef.current = null;
      }
    };
  }, [connected, assistantMode]);

  // ── Auto-validation loop for DIY steps ──────────────────────────────
  useEffect(() => {
    if (!connected || assistantMode !== "diy" || !visualInputEnabled || !aiReadyForFrames) {
      return;
    }

    const intervalId = window.setInterval(async () => {
      const frame = await captureCurrentFrame(true); // force high-res for validation
      if (frame) {
        validateCurrentStep(frame.image, frame.mimeType);
      }
    }, 10000); // Validate every 10 seconds

    return () => window.clearInterval(intervalId);
  }, [connected, assistantMode, visualInputEnabled, aiReadyForFrames, validateCurrentStep]);

  useEffect(() => {
    const Recognition = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Recognition) {
      setSpeechSupported(false);
      return;
    }

    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onstart = () => {
      setListening(true);
      spokenTextRef.current = "";
    };
    recognition.onresult = (event) => {
      let transcript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        transcript += event.results[index][0].transcript;
      }
      spokenTextRef.current = transcript.trim();
      setPrompt(transcript.trim());
    };
    recognition.onerror = () => {
      setListening(false);
      pushToTalkKeyActiveRef.current = false;
    };
    recognition.onend = () => {
      // Clear state immediately so hold-to-talk is available for the next press
      setListening(false);
      pushToTalkKeyActiveRef.current = false;
      const transcript = spokenTextRef.current.trim();
      spokenTextRef.current = "";
      setPrompt("");

      // Fire-and-forget: send the transcript without blocking the button
      if (transcript) {
        void (async () => {
          const frame = await captureFrameRef.current(true);
          sendTextRef.current(transcript, frame ?? undefined);
        })();
      }
    };

    recognitionRef.current = recognition;
    setSpeechSupported(true);

    return () => {
      recognition.stop();
      recognitionRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || isEditableTarget(event.target)) {
        return;
      }
      if (event.code !== "ControlRight") {
        return;
      }
      if (!connected || !speechSupported || listening || pushToTalkKeyActiveRef.current || assistantMode === "diy") {
        return;
      }
      pushToTalkKeyActiveRef.current = true;
      spokenTextRef.current = "";
      recognitionRef.current?.start();
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.code !== "ControlRight") {
        return;
      }
      pushToTalkKeyActiveRef.current = false;
      if (listening) {
        recognitionRef.current?.stop();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [connected, listening, speechSupported, assistantMode]);

  async function captureCurrentFrame(force: boolean): Promise<{ image: string; mimeType: string } | null> {
    if (!connected || !visualInputEnabled || !aiReadyForFrames) {
      return null;
    }
    const now = Date.now();
    if (!force && now - lastFrameCapturedAtRef.current < 1500) {
      return null;
    }

    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.videoWidth === 0 || video.videoHeight === 0) {
      return null;
    }

    const maxWidth = screenShareEnabled ? 1280 : 720;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));

    const context = canvas.getContext("2d");
    if (!context) {
      return null;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((result) => resolve(result), "image/jpeg", screenShareEnabled ? 0.72 : 0.74);
    });
    if (!blob) {
      return null;
    }

    const image = await blobToBase64(blob);
    lastFrameCapturedAtRef.current = now;
    return { image, mimeType: "image/jpeg" };
  }

  async function attachStream(stream: MediaStream) {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
    }
  }

  async function startCamera() {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
      audio: false,
    });
    mediaStreamRef.current = stream;
    setCameraEnabled(true);
    setScreenShareEnabled(false);
    await attachStream(stream);
  }

  function stopCamera(clearVideo = true) {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    setCameraEnabled(false);
    if (clearVideo && videoRef.current && !screenStreamRef.current) {
      videoRef.current.srcObject = null;
    }
  }

  function stopScreenShare(clearVideo = true) {
    screenStreamRef.current?.getTracks().forEach((track) => track.stop());
    screenStreamRef.current = null;
    setScreenShareEnabled(false);
    if (clearVideo && videoRef.current && !mediaStreamRef.current) {
      videoRef.current.srcObject = null;
    }
  }

  async function toggleCamera() {
    if (cameraEnabled) {
      stopCamera();
      return;
    }
    if (screenStreamRef.current) {
      stopScreenShare(false);
    }
    await startCamera().catch(() => setCameraEnabled(false));
    lastFrameCapturedAtRef.current = 0;
  }

  async function toggleScreenShare() {
    if (screenStreamRef.current) {
      stopScreenShare();
      return;
    }
    if (mediaStreamRef.current) {
      stopCamera(false);
    }
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const [videoTrack] = stream.getVideoTracks();
    if (videoTrack) {
      videoTrack.onended = () => {
        stopScreenShare();
      };
    }
    screenStreamRef.current = stream;
    setScreenShareEnabled(true);
    setCameraEnabled(false);
    await attachStream(stream);
    lastFrameCapturedAtRef.current = 0;
  }

  function startTalking() {
    if (!connected || !speechSupported || listening) {
      return;
    }
    spokenTextRef.current = "";
    pushToTalkKeyActiveRef.current = true;
    recognitionRef.current?.start();
  }

  function stopTalking() {
    pushToTalkKeyActiveRef.current = false;
    if (!listening) {
      return;
    }
    recognitionRef.current?.stop();
  }

  function startSession() {
    connect();
  }

  function stopSession() {
    disconnect();
    stopTalking();
    stopScreenShare(false);
    stopCamera();
  }

  async function handleSend() {
    if (!prompt.trim()) {
      return;
    }
    const frame = await captureCurrentFrame(true);
    sendText(prompt, frame ?? undefined);
    setPrompt("");
  }

  function handleModeChange(mode: AssistantMode) {
    updateAssistantMode(mode);
  }

  return (
    <main className="mx-auto min-h-screen max-w-7xl px-4 py-6 md:px-6 lg:px-8">
      <div className="mb-6 flex flex-col gap-4 rounded-[2rem] border border-black/10 bg-[rgba(255,248,236,0.82)] p-6 shadow-panel backdrop-blur md:flex-row md:items-end md:justify-between">
        <div>
          <div className="mb-3 flex items-center gap-2">
            <StatusPill
              label={connected ? "Live" : status}
              tone={connected ? "success" : status === "error" ? "warning" : "neutral"}
            />
            <StatusPill
              label={sessionRuntime}
              tone={sessionRuntime === "MockGeminiLiveSession" ? "warning" : "neutral"}
            />
            <StatusPill
              label={assistantMode.toUpperCase()}
              tone={assistantMode === "diy" ? "success" : "neutral"}
            />
            <StatusPill
              label={aiReadyForFrames ? "Vision Ready" : "Reconnecting"}
              tone={aiReadyForFrames ? "success" : "warning"}
            />
          </div>
          <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-ink md:text-5xl">
            HoneyAI Live
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-black/65 md:text-base">
            A real-time multimodal instructor that watches, listens, and guides users through
            physical tasks safely.
          </p>
        </div>
        <div className="grid gap-3 text-sm text-black/65">
          <div className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-pine" />
            Stores summaries only, not raw camera footage.
          </div>
          <div className="flex items-center gap-2">
            <Camera size={18} className="text-ember" />
            Each question now carries one fresh visual snapshot instead of a separate live frame upload.
          </div>
          <div className="flex items-center gap-2">
            <Mic size={18} className="text-honey" />
            Hold to talk works by button or by holding Right Ctrl on the keyboard. Browser apps cannot reliably capture the hardware Fn key.
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <section className="space-y-6">
          <ControlBar
            status={status}
            connected={connected}
            cameraEnabled={cameraEnabled}
            listening={listening}
            screenShareEnabled={screenShareEnabled}
            speechSupported={speechSupported}
            assistantMode={assistantMode}
            onStart={startSession}
            onStop={stopSession}
            onToggleCamera={toggleCamera}
            onToggleScreenShare={toggleScreenShare}
            onModeChange={handleModeChange}
            onTalkStart={startTalking}
            onTalkStop={stopTalking}
            prompt={prompt}
            onPromptChange={setPrompt}
            onSend={handleSend}
          />

          <div className="overflow-hidden rounded-4xl border border-black/10 bg-[#201b17] shadow-panel">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4 text-white">
              <div>
                <h2 className="text-lg font-semibold">Live feed</h2>
                <p className="text-sm text-white/60">Keep ports, labels, work surfaces, or your shared screen centered.</p>
              </div>
              {!visualInputEnabled ? (
                <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/70">
                  <AlertTriangle size={16} />
                  Visual input off
                </div>
              ) : !aiReadyForFrames ? (
                <div className="inline-flex items-center gap-2 rounded-full bg-ember/20 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/80">
                  Reconnecting AI
                </div>
              ) : screenShareEnabled ? (
                <div className="inline-flex items-center gap-2 rounded-full bg-honey/20 px-3 py-2 text-xs uppercase tracking-[0.18em] text-honey">
                  Shared screen
                </div>
              ) : (
                <div className="inline-flex items-center gap-2 rounded-full bg-pine/20 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white">
                  Camera live
                </div>
              )}
            </div>
            <div className="relative aspect-video w-full bg-gradient-to-br from-[#2f2b26] to-[#161311]">
              <video
                ref={videoRef}
                className={`h-full w-full ${screenShareEnabled ? "object-contain bg-black" : "object-cover"}`}
                muted
                playsInline
                autoPlay
              />
              {!visualInputEnabled ? (
                <div className="absolute inset-0 grid place-items-center">
                  <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-5 text-center text-white/75 backdrop-blur">
                    Enable the camera or screen share to let HoneyAI inspect the task.
                  </div>
                </div>
              ) : null}
              <canvas ref={canvasRef} className="hidden" />
            </div>
          </div>

          <ConversationLog messages={messages} />
        </section>

        <section className="space-y-6">
          <TaskProgress
            plan={plan}
            assistantMode={assistantMode}
            onMarkStep={updateStep}
            onRegenerate={regeneratePlan}
            isValidating={isValidating}
          />
          <div className="rounded-4xl border border-black/10 bg-white/75 p-5 shadow-panel backdrop-blur">
            <h2 className="text-lg font-semibold">How to use</h2>
            <ol className="mt-4 space-y-3 text-sm leading-6 text-black/70">
              <li>1. Start AI, then enable camera or screen share.</li>
              <li>2. Pick General mode to ask visual questions or DIY mode for guided repair and setup help.</li>
              <li>3. Hold the talk button or hold Right Ctrl, then release to send.</li>
              <li>4. In DIY mode, use Mark done or Mark blocked as you complete each step.</li>
            </ol>
          </div>
        </section>
      </div>
    </main>
  );
}
