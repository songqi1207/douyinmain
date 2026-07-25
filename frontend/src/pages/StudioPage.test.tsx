import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Job, Workflow } from "../types";
import { StudioPage } from "./StudioPage";

const api = vi.hoisted(() => ({
  createJob: vi.fn(),
  fetchDraftKeyRenderStatus: vi.fn(),
  fetchJob: vi.fn(),
  fetchJobs: vi.fn(),
  fetchSiteSummary: vi.fn(),
  fetchWorkflows: vi.fn(),
  retryJob: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, ...api };
});

vi.mock("../auth", () => ({
  useAuth: () => ({
    user: {
      id: "user-1",
      username: "creator",
      email: "creator@example.test",
      role: "user",
      must_change_password: false,
    },
    workflow_favorites: [],
    voice_favorites: [],
    loading: false,
    refresh: vi.fn(),
    setAuth: vi.fn(),
    logout: vi.fn(),
  }),
}));

const workflows = ["OWN01", "OWN02", "OWN03"].map((code): Workflow => ({
  code,
  name: code,
  description: code,
  category: "自有工作流",
  categories: ["自有工作流"],
  tags: [],
  preview: false,
  preview_mime: "",
  status: "online",
  input_schema: [{ name: "theme", label: "主题", type: "text", required: true }],
  output_type: "draft",
  generation_mode: "draft",
  stats: { views: 0, favorites: 0, downloads: 0, runs: 0 },
}));

const queuedJob: Job = {
  id: "job-1",
  workflow_code: "OWN02",
  category: "自有工作流",
  display_title: "中华",
  status: "queued",
  stage: "queued",
  progress: 0,
  results: [],
  created_at: 1,
  updated_at: 1,
};

describe("StudioPage", () => {
  beforeEach(() => {
    localStorage.clear();
    api.fetchWorkflows.mockResolvedValue({ items: workflows, total: 3 });
    api.fetchDraftKeyRenderStatus.mockResolvedValue({
      configured: true,
      device_online: true,
      central_configured: false,
      devices: [],
      message: "本机助手在线",
    });
    api.fetchSiteSummary.mockResolvedValue({
      catalog: { workflows: 3, online_workflows: 3, categories: 1, voices: 2 },
      activity: { users: 1, favorites: 0, views: 0, downloads: 0, runs: 0 },
      jobs: { total: 0, succeeded: 0, active: 0, failed: 0 },
      voice_service: { provider: "external", available: true, message: "ok" },
    });
    api.fetchJobs.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 4 });
    api.createJob.mockResolvedValue({ job: queuedJob });
  });

  it("submits only the selected workflow and theme", async () => {
    render(<MemoryRouter><StudioPage /></MemoryRouter>);
    await screen.findByText("已发布");
    fireEvent.click(screen.getByRole("tab", { name: /香烟故事/ }));
    fireEvent.change(screen.getByPlaceholderText("输入香烟名称"), { target: { value: "中华" } });
    fireEvent.click(screen.getByRole("button", { name: "一键生成视频" }));

    await waitFor(() => expect(api.createJob).toHaveBeenCalledWith(
      "OWN02",
      "自有工作流",
      { theme: "中华" },
    ));
    expect(await screen.findByText("等待执行")).toBeInTheDocument();
  });

  it("shows device readiness before submission", async () => {
    api.fetchDraftKeyRenderStatus.mockResolvedValueOnce({
      configured: false,
      device_online: false,
      central_configured: false,
      devices: [],
      message: "需要配对",
    });
    render(<MemoryRouter><StudioPage /></MemoryRouter>);
    expect(await screen.findByText("需要完成一次配对")).toBeInTheDocument();
  });
});
