export type ConnectionStatus = "idle" | "connecting" | "connected" | "error";
export type AssistantMode = "general" | "diy";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
};

export type TaskStep = {
  id: string;
  title: string;
  instruction: string;
  status: "pending" | "in_progress" | "completed" | "blocked";
  validation_hint: string;
  last_validation_reasoning?: string | null;
};

export type TaskPlan = {
  goal: string;
  steps: TaskStep[];
  current_step_id?: string | null;
};

export type ServerMessage = {
  type: string;
  text?: string;
  message?: string;
  audio?: string;
  mime_type?: string;
  data?: Record<string, unknown>;
};
