import type { AuthUser, Job, RegistrationApplication, SiteSummary, VoiceCatalog, Workflow } from "./types";

type ApiErrorShape = { detail?: string | { message?: string }; message?: string };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = (await response.json().catch(() => ({}))) as ApiErrorShape & T;
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === "string" ? detail : detail?.message || payload.message || "请求失败";
    throw new Error(message);
  }
  return payload as T;
}

export async function fetchCategories() {
  return request<{ categories: Array<{ name: string; count: number }>; total: number }>("/api/v1/categories");
}

export async function fetchWorkflows(params: { category: string; q: string; sort: string }) {
  const query = new URLSearchParams({ ...params, page_size: "100" });
  return request<{ items: Workflow[]; total: number }>(`/api/v1/workflows?${query}`);
}

export async function fetchJobs(page = 1) {
  const query = new URLSearchParams({ page: String(page), page_size: "20" });
  return request<{ items: Job[]; total: number; page: number; page_size: number }>(`/api/v1/jobs?${query}`);
}

export async function fetchWorkflow(code: string, category: string) {
  const query = new URLSearchParams({ category });
  return request<{ workflow: Workflow }>(`/api/v1/workflows/${encodeURIComponent(code)}?${query}`);
}

export async function uploadAsset(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<{ asset: { id: string; name: string; mime_type: string; size_bytes: number; url: string } }>(
    "/api/v1/assets",
    { method: "POST", body }
  );
}

export async function createJob(workflowCode: string, category: string, inputs: Record<string, unknown>) {
  return request<{ job: Job }>("/api/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow_code: workflowCode, category, inputs })
  });
}

export async function fetchJob(jobId: string) {
  return request<{ job: Job }>(`/api/v1/jobs/${jobId}`);
}

export async function retryJob(jobId: string) {
  return request<{ job: Job }>(`/api/v1/jobs/${jobId}/retry`, { method: "POST" });
}

export async function fetchDraftKeyResult(url: string) {
  return request<Record<string, unknown>>(url);
}

export type LocalDraftReport = {
  draft_id: string;
  draft_name?: string;
  draft_dir: string;
  message?: string;
  already_imported?: boolean;
};

export async function importDraftKeyLocally(bridgeUrl: string, key: Record<string, unknown>) {
  const base = bridgeUrl.trim().replace(/\/+$/, "");
  const endpoint = base.endsWith("/api/tools/create_draft_from_key")
    ? base
    : `${base}/api/tools/create_draft_from_key`;
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, force: false }),
    });
  } catch {
    throw new Error(`无法连接 Windows 草稿桥接服务：${endpoint}。请确认 app.py/EXE 已启动，并检查浏览器是否拦截了本地网络请求。`);
  }
  const payload = (await response.json().catch(() => ({}))) as Partial<LocalDraftReport> & { message?: string };
  if (!response.ok) throw new Error(payload.message || `本地草稿生成失败（HTTP ${response.status}）`);
  if (!payload.draft_id || !payload.draft_dir) throw new Error("本地桥接服务没有返回 draft_id 或 draft_dir");
  return payload as LocalDraftReport;
}

export type AuthState = {
  user: AuthUser | null;
  workflow_favorites: string[];
  voice_favorites: string[];
};

export async function fetchMe() {
  return request<AuthState>("/api/v1/auth/me");
}

export async function login(email: string, password: string) {
  return request<AuthState>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function register(email: string) {
  return request<{ application: RegistrationApplication; message: string }>("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
}

export async function fetchRegistrationApplications(status = "pending") {
  const query = new URLSearchParams({ status });
  return request<{
    items: RegistrationApplication[];
    total: number;
    email_service: { configured: boolean; sender?: string | null; message: string };
  }>(`/api/v1/admin/registration-applications?${query}`);
}

export async function approveRegistration(applicationId: string) {
  return request<{ application: RegistrationApplication; message: string }>(
    `/api/v1/admin/registration-applications/${encodeURIComponent(applicationId)}/approve`,
    { method: "POST" },
  );
}

export async function rejectRegistration(applicationId: string) {
  return request<{ application: RegistrationApplication; message: string }>(
    `/api/v1/admin/registration-applications/${encodeURIComponent(applicationId)}/reject`,
    { method: "POST" },
  );
}

export async function logout() {
  const response = await fetch("/api/v1/auth/logout", { method: "POST" });
  if (!response.ok) throw new Error("退出失败");
}

export async function toggleFavorite(resourceType: "workflow" | "voice", resourceId: string) {
  return request<{ selected: boolean; resource_id: string; favorites: number }>(`/api/v1/favorites/${resourceType}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resource_id: resourceId }),
  });
}

export async function fetchVoices() {
  return request<VoiceCatalog>("/api/v1/voices");
}

export async function fetchSiteSummary() {
  return request<SiteSummary>("/api/v1/site-summary");
}

export async function generateSpeech(text: string, voiceId: string, speedRatio: number) {
  return request<{ audio: { url: string; duration: number; message: string } }>("/api/v1/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice_id: voiceId, speed_ratio: speedRatio }),
  });
}
