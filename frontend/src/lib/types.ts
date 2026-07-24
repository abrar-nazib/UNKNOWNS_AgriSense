// Shared domain types, mirrored from docs/API_CONTRACT.md (frozen).

export interface Address {
  division_name: string;
  division_code: string;
  district_name: string;
  district_code: string;
  upazila_name: string;
  upazila_code: string;
}

export interface AuthUser {
  id: number;
  username: string;
  phone: string;
  address: Address;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
}

export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  result: string;
}

export type Role = "user" | "assistant";

export interface Message {
  id: number;
  role: Role;
  content: string;
  tool_trace: ToolCall[];
  model: string;
  created_at: string;
}

export interface Session {
  id: number;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface SessionsResponse {
  results: Session[];
}

export interface MessagesResponse {
  session_id: number;
  results: Message[];
}

// ---- SSE stream frames (discriminated union on `type`) ----

export interface SessionFrame {
  type: "session";
  session_id: number;
}
export interface MessageFrame {
  type: "message";
  message: Message;
}
export interface MessageUpdateFrame {
  type: "message_update";
  message: Message;
}
export interface ProgressFrame {
  type: "progress";
  stage: string;
  detail: string;
}
export interface DoneFrame {
  type: "done";
}
export interface ErrorFrame {
  type: "error";
  detail: string;
  session_id?: number;
}

export type StreamFrame =
  | SessionFrame
  | MessageFrame
  | MessageUpdateFrame
  | ProgressFrame
  | DoneFrame
  | ErrorFrame;
