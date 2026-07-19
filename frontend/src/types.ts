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
  generation_mode: "workflow_template" | "video";
  stats: { views: number; favorites: number; downloads: number; runs: number };
  created_at?: string | null;
  updated_at?: string | null;
};

export type JobResult = {
  type: "image" | "video" | "draft";
  url: string;
  poster_url?: string | null;
  downloadable: boolean;
};

export type Job = {
  id: string;
  workflow_code: string;
  category: string;
  status: "queued" | "running" | "rendering" | "succeeded" | "failed";
  stage: string;
  progress: number;
  results: JobResult[];
  error?: { code: string; message: string } | null;
  created_at: number;
  updated_at: number;
};

export type AuthUser = { id: string; username: string; email?: string | null; role: "user" | "admin"; must_change_password?: boolean };

export type RegistrationApplication = {
  id: string;
  email: string;
  status: "pending" | "delivering" | "approved" | "rejected";
  delivery_status: "not_sent" | "sending" | "sent" | "failed";
  delivery_error?: string | null;
  reviewed_at?: number | null;
  created_at: number;
  updated_at: number;
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
