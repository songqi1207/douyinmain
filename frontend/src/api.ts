import type {
  AuthUser,
  AdminJobPage,
  AdminWorkflowPricing,
  Job,
  JobLogEntry,
  JobPage,
  RegistrationApplication,
  RenderDevice,
  RenderStatus,
  RuntimeSettings,
  SiteSummary,
  UserQuota,
  VoiceCatalog,
  Workflow,
  WorkflowPricing,
} from "./types";

type ApiErrorShape = {
  detail?: string | { code?: string; message?: string; errors?: unknown };
  message?: string;
};

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(message: string, status = 0, code = "request_failed", details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError("网络连接失败，请检查服务是否可用", 0, "network_error");
  }
  const payload = (await response.json().catch(() => ({}))) as ApiErrorShape & T;
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === "string"
      ? detail
      : detail?.message || payload.message || "请求失败";
    const code = typeof detail === "object" && detail?.code
      ? detail.code
      : `http_${response.status}`;
    throw new ApiError(
      message,
      response.status,
      code,
      typeof detail === "object" ? detail.errors : undefined,
    );
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

export async function fetchWorkflow(code: string, category: string) {
  const query = new URLSearchParams({ category });
  return request<{ workflow: Workflow }>(`/api/v1/workflows/${encodeURIComponent(code)}?${query}`);
}

export async function fetchJobs(params: {
  page?: number;
  pageSize?: number;
  status?: string;
  workflowCode?: string;
} = {}) {
  const query = new URLSearchParams({
    page: String(params.page || 1),
    page_size: String(params.pageSize || 20),
  });
  if (params.status && params.status !== "all") query.set("status", params.status);
  if (params.workflowCode) query.set("workflow_code", params.workflowCode);
  return request<JobPage>(`/api/v1/jobs?${query}`, { cache: "no-store" });
}

export async function fetchJob(jobId: string) {
  return request<{ job: Job }>(`/api/v1/jobs/${jobId}`, { cache: "no-store" });
}

export async function fetchJobLogs(jobId: string, afterId = 0) {
  const query = afterId > 0 ? `?after_id=${afterId}` : "";
  return request<{ items: JobLogEntry[] }>(`/api/v1/jobs/${jobId}/logs${query}`, { cache: "no-store" });
}

export async function createJob(workflowCode: string, category: string, inputs: Record<string, unknown>) {
  return request<{ job: Job }>("/api/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow_code: workflowCode, category, inputs }),
  });
}

export async function retryJob(jobId: string) {
  return request<{ job: Job }>(`/api/v1/jobs/${jobId}/retry`, { method: "POST" });
}

export async function deleteJobVideo(jobId: string) {
  return request<{ job: Job; quota: UserQuota; released_bytes: number; message: string }>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/video`,
    { method: "DELETE" },
  );
}

export async function fetchAccountQuota() {
  return request<{ quota: UserQuota }>("/api/v1/account/quota", { cache: "no-store" });
}

export async function fetchAdminUserQuotas() {
  return request<{ items: UserQuota[]; total: number }>("/api/v1/admin/user-quotas", { cache: "no-store" });
}

export async function fetchAdminJobs(params: {
  page: number;
  pageSize: number;
  status?: string;
  workflowCode?: string;
  userId?: string;
  q?: string;
}) {
  const query = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.pageSize),
    status: params.status || "",
    workflow_code: params.workflowCode || "",
    user_id: params.userId || "",
    q: params.q || "",
  });
  return request<AdminJobPage>(`/api/v1/admin/jobs?${query}`, { cache: "no-store" });
}

export async function adjustAdminUserQuota(
  userId: string,
  payload: { points_delta: number; storage_limit_gb?: number; detail?: string },
) {
  return request<{ quota: UserQuota; message: string }>(
    `/api/v1/admin/user-quotas/${encodeURIComponent(userId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function revealAdminUserPassword(userId: string, adminPassword: string) {
  return request<{ user_id: string; password: string }>(
    `/api/v1/admin/users/${encodeURIComponent(userId)}/password/reveal`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ admin_password: adminPassword }),
      cache: "no-store",
    },
  );
}

export async function resetAdminUserPassword(
  userId: string,
  adminPassword: string,
  newPassword = "",
) {
  return request<{ user_id: string; password: string }>(
    `/api/v1/admin/users/${encodeURIComponent(userId)}/password/reset`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ admin_password: adminPassword, new_password: newPassword }),
      cache: "no-store",
    },
  );
}

export async function fetchAdminWorkflowPricing() {
  return request<{ items: AdminWorkflowPricing[]; total: number }>(
    "/api/v1/admin/workflow-pricing",
    { cache: "no-store" },
  );
}

export async function updateAdminWorkflowPricing(
  workflowCode: string,
  payload: { coze_cost_points: number; mihe_cost_points: number },
) {
  return request<{ pricing: WorkflowPricing; message: string }>(
    `/api/v1/admin/workflow-pricing/${encodeURIComponent(workflowCode)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function uploadAsset(file: File) {
  const body = new FormData();
  body.append("file", file);
  return request<{ asset: { id: string; name: string; mime_type: string; size_bytes: number; url: string } }>(
    "/api/v1/assets",
    { method: "POST", body },
  );
}

export async function createDraftKeyRender(draftKey: Record<string, unknown>) {
  return request<{ job: Job }>("/api/v1/draft-key-renders", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ draft_key: draftKey }),
  });
}

export async function fetchDraftKeyRenderStatus() {
  return request<RenderStatus>("/api/v1/draft-key-renders/status");
}

export async function fetchRenderDevices() {
  return request<{ items: RenderDevice[]; online: boolean }>("/api/v1/render-devices");
}

export async function createRenderDevicePairingCode() {
  return request<{ code: string; expires_at: number }>("/api/v1/render-devices/pairing-codes", {
    method: "POST",
  });
}

export async function revokeRenderDevice(deviceId: string) {
  return request<void>(`/api/v1/render-devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
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

export async function changePassword(currentPassword: string, newPassword: string) {
  return request<AuthState>("/api/v1/auth/password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export async function register(email: string, inviteCode = "") {
  return request<{ application: RegistrationApplication; message: string }>("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, invite_code: inviteCode }),
  });
}

export async function logout() {
  await request<void>("/api/v1/auth/logout", { method: "POST" });
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

export async function fetchRuntimeSettings() {
  return request<RuntimeSettings>("/api/v1/admin/runtime-settings", { cache: "no-store" });
}

export async function updateRuntimeSettings(payload: {
  mihe_key?: string;
  clear_mihe_key?: boolean;
  workflow_ids: Record<string, string>;
  workflow_inputs: Record<string, Record<string, unknown>>;
}) {
  return request<RuntimeSettings>("/api/v1/admin/runtime-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function toggleFavorite(resourceType: "workflow" | "voice", resourceId: string) {
  return request<{ selected: boolean; resource_id: string; favorites: number }>(
    `/api/v1/favorites/${resourceType}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resource_id: resourceId }),
    },
  );
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
