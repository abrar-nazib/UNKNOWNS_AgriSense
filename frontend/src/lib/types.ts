// Shared domain types, mirrored from docs/API_CONTRACT.md (frozen).

export interface Address {
  division_name: string;
  division_code: string;
  district_name: string;
  district_code: string;
  upazila_name: string;
  upazila_code: string;
  union_name: string;
  union_code: string;
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

export interface BillingPlan {
  id: "free" | "plus" | "pro";
  name: string;
  amount_bdt: number;
  billing_cycle: "none" | "monthly";
  features: string[];
}

export interface BillingPlansResponse {
  results: BillingPlan[];
  provider: "mock" | "bdapps";
  subscribable_plan_ids: Array<"plus" | "pro">;
}

export interface Subscription {
  plan_id: "free" | "plus" | "pro";
  status: "active" | "inactive" | "cancelled";
  provider: "internal" | "mock" | "bdapps";
  provider_status: string;
  subscriber_id: string;
  amount_bdt: number;
  billing_cycle: "none" | "monthly";
  started_at: string | null;
  cancelled_at: string | null;
}

export interface BillingOtpStart {
  challenge_id: string;
  expires_in_seconds: number;
  status_code: string;
  status_detail: string;
  demo_otp: string | null;
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
