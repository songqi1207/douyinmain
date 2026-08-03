export type InputField = {
  name: string;
  label: string;
  type: "text" | "textarea" | "number" | "select" | "image" | "video" | "audio" | "file" | "notice";
  required?: boolean;
  multiple?: boolean;
  max_files?: number;
  accept?: string[];
  placeholder?: string;
  default?: string | number;
  min?: number;
  max?: number;
  options?: Array<{ label: string; value: string }>;
};

export type WorkflowPricing = {
  workflow_code: string;
  coze_cost_points: number;
  mihe_cost_points: number;
  provider_cost_points: number;
  billing_multiplier: number;
  price_points: number;
  updated_at: number;
};

export type Workflow = {
  code: string;
  name: string;
  description: string;
  category: string;
  categories: string[];
  tags: string[];
  preview: boolean;
  preview_mime: string;
  preview_url?: string | null;
  status: "online" | "coming_soon";
  input_schema: InputField[];
  output_type: "image" | "video" | "draft";
  generation_mode: "workflow_template" | "draft" | "video";
  stats: { views: number; favorites: number; downloads: number; runs: number };
  pricing?: Pick<WorkflowPricing, "workflow_code" | "price_points">;
  created_at?: string | null;
  updated_at?: string | null;
};

export type JobResult = {
  type: "image" | "video" | "draft";
  format?: "draft_key" | "workflow_template";
  url: string;
  download_url?: string;
  poster_url?: string | null;
  downloadable: boolean;
  remote_draft_id?: string;
};

export type Job = {
  id: string;
  workflow_code: string;
  category: string;
  display_title: string;
  status: "queued" | "running" | "rendering" | "succeeded" | "failed";
  stage: string;
  failed_stage?: string | null;
  progress: number;
  price_points?: number;
  billing?: {
    status: "reserved" | "charged" | "refunded";
    price_points: number;
    charged_points: number;
    reserved_points: number;
    refunded_points: number;
  };
  results: JobResult[];
  error?: { code: string; message: string } | null;
  created_at: number;
  updated_at: number;
};

export type RenderDevice = {
  id: string;
  name: string;
  platform: string;
  capabilities: Record<string, unknown>;
  online: boolean;
  last_seen?: number | null;
  created_at: number;
};

export type AuthUser = { id: string; username: string; email?: string | null; role: "user" | "admin"; must_change_password?: boolean; invite_code?: string | null };

export type RuntimeWorkflowSetting = {
  code: string;
  name: string;
  category: string;
  workflow_id: string;
  input_schema: InputField[];
  input_defaults: Record<string, unknown>;
};

export type RuntimeSettings = {
  mihe_key: {
    configured: boolean;
    masked: string;
  };
  workflows: RuntimeWorkflowSetting[];
  message?: string;
};

export type RegistrationApplication = {
  id: string;
  email: string;
  status: "pending" | "delivering" | "approved" | "rejected";
  delivery_status: "not_sent" | "sending" | "sent" | "failed";
  delivery_error?: string | null;
  reviewed_at?: number | null;
  created_at: number;
  updated_at: number;
  invite_code?: string | null;
};

export type Voice = {
  id: string;
  name: string;
  gender: "female" | "male" | "boy" | "girl" | "neutral";
  gender_label: string;
  language: string;
  description: string;
  model: string;
  provider: "external" | "local-system";
  available: boolean;
};

export type VoiceCatalog = {
  voices: Voice[];
  total: number;
  provider: "external" | "local-system";
  available: boolean;
  message: string;
};

export type SiteSummary = {
  catalog: { workflows: number; online_workflows: number; categories: number; voices: number };
  activity: { users: number; favorites: number; views: number; downloads: number; runs: number };
  jobs: { total: number; succeeded: number; active: number; failed: number };
  voice_service: { provider: string; available: boolean; message: string };
};

export type RenderStatus = {
  configured: boolean;
  device_online: boolean;
  central_configured: boolean;
  shared_device?: boolean;
  latest_helper_version?: string;
  devices: RenderDevice[];
  message: string;
};

export type JobLogEntry = {
  id: number;
  level: string;
  message: string;
  created_at: number;
};

export type JobPage = {
  items: Job[];
  total: number;
  page: number;
  page_size: number;
};

export type AdminJob = Job & {
  user: {
    id: string;
    username: string;
    email?: string | null;
    role: "user" | "admin";
    active: boolean;
  };
};

export type AdminJobPage = {
  items: AdminJob[];
  users: AdminJob["user"][];
  summary: {
    total: number;
    users: number;
    succeeded: number;
    failed: number;
    active: number;
    points: number;
  };
  total: number;
  page: number;
  page_size: number;
};

export type QuotaLedgerEntry = {
  id: string;
  job_id?: string | null;
  event_type: "reserve" | "consume" | "refund" | "adjust" | "invite_reward" | "welcome_bonus" | "storage_reserve" | "storage_release";
  units: number;
  balance_after: number;
  detail?: string | null;
  created_at: number;
};

export type UserQuota = {
  user: {
    id: string;
    username: string;
    email?: string | null;
    role: "user" | "admin";
    active: boolean;
  };
  unlimited: boolean;
  generation_balance: number;
  generation_reserved: number;
  generation_consumed: number;
  points_balance: number;
  points_reserved: number;
  storage_points_reserved: number;
  points_reserved_total: number;
  points_consumed: number;
  storage_used_bytes: number;
  storage_limit_bytes: number;
  storage_available_bytes: number;
  can_generate: boolean;
  billing_multiplier: number;
  invite: {
    code: string;
    invited_count: number;
    rewarded_points: number;
    inviter_reward_points: number;
    invitee_reward_points: number;
  };
  ledger?: QuotaLedgerEntry[];
};

export type AdminWorkflowPricing = {
  workflow: Pick<Workflow, "code" | "name" | "status" | "categories">;
  pricing: WorkflowPricing;
};

export type ProviderUsageSnapshot = {
  days: number;
  since: number;
  balance_source: "estimated_pricing";
  balance_available: boolean;
  totals: { calls: number; successes: number; failures: number; estimated_points: number };
  by_provider: Record<string, { calls: number; successes: number; failures: number; estimated_points: number; avg_elapsed_ms: number }>;
  by_workflow: Array<{ workflow_code: string; provider: string; calls: number; successes: number; failures: number; estimated_points: number; avg_elapsed_ms: number }>;
  recent_errors: Array<{ id: string; job_id?: string | null; workflow_code: string; provider: string; status: string; estimated_points: number; http_status?: number | null; elapsed_ms: number; error_code?: string | null; error_message?: string | null; created_at: number }>;
};

export type SystemHealthCheck = {
  id: string;
  trigger: string;
  checked_at: number;
  overall: "ok" | "warning" | "error";
  checks: Array<{
    name: string;
    status: "ok" | "warning" | "error";
    code: string;
    message: string;
    details?: Record<string, unknown>;
  }>;
};
