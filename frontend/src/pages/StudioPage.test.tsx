import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Job, Workflow } from "../types";
import { StudioPage } from "./StudioPage";

const api = vi.hoisted(() => ({
  createJob: vi.fn(),
  fetchDraftKeyRenderStatus: vi.fn(),
  fetchJob: vi.fn(),
  fetchJobs: vi.fn(),
  fetchRuntimeSettings: vi.fn(),
  fetchSiteSummary: vi.fn(),
  fetchWorkflows: vi.fn(),
  retryJob: vi.fn(),
  updateRuntimeSettings: vi.fn(),
}));
const authState = vi.hoisted(() => ({ role: "user" }));

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
      role: authState.role,
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
  generation_mode: "workflow_template",
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

const runtimeSettings = {
  mihe_key: { configured: true, masked: "****1234" },
  workflows: [
    {
      code: "OWN01", name: "书单视频", category: "自有工作流", workflow_id: "11111111",
      input_schema: [{ name: "author", label: "默认作者", type: "text" as const, default: "佚名" }],
      input_defaults: { author: "佚名" },
    },
    {
      code: "OWN02", name: "香烟故事", category: "自有工作流", workflow_id: "22222222",
      input_schema: [{ name: "left", label: "左侧提示文字", type: "text" as const }],
      input_defaults: { left: "未成年人禁止吸烟" },
    },
    {
      code: "OWN03", name: "神话人物", category: "自有工作流", workflow_id: "33333333",
      input_schema: [
        { name: "shuliang", label: "默认分镜数量", type: "number" as const, default: 10, min: 1, max: 22 },
        {
          name: "yinse",
          label: "默认配音音色",
          type: "select" as const,
          default: "7620288417930297386",
          options: [{ label: "爽快思思 / Skye", value: "7620288417930297386" }],
        },
      ],
      input_defaults: { shuliang: 10, yinse: "7620288417930297386" },
    },
  ],
};

describe("StudioPage", () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    authState.role = "user";
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
    api.fetchRuntimeSettings.mockResolvedValue(runtimeSettings);
    api.createJob.mockResolvedValue({ job: queuedJob });
    api.updateRuntimeSettings.mockResolvedValue({ ...runtimeSettings, message: "运行配置已保存并立即生效" });
  });

  it("submits only the selected workflow and theme", async () => {
    render(<MemoryRouter><StudioPage /></MemoryRouter>);
    fireEvent.click(screen.getByRole("tab", { name: /香烟故事/ }));
    fireEvent.change(await screen.findByPlaceholderText("输入香烟名称"), { target: { value: "中华" } });
    fireEvent.click(screen.getByRole("button", { name: /一键生成视频/ }));

    await waitFor(() => expect(api.createJob).toHaveBeenCalledWith(
      "OWN02",
      "自有工作流",
      { theme: "中华" },
    ));
    expect(await screen.findByText("等待执行")).toBeInTheDocument();
  });

  it("keeps device diagnostics hidden for regular users", async () => {
    api.fetchDraftKeyRenderStatus.mockResolvedValueOnce({
      configured: false,
      device_online: false,
      central_configured: false,
      devices: [],
      message: "需要配对",
    });
    render(<MemoryRouter><StudioPage /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: "完成准备后生成" })).toBeInTheDocument();
    expect(screen.queryByText("需要完成一次配对")).not.toBeInTheDocument();
  });

  it("keeps the recent creation progress in sync with the active job", async () => {
    const staleRecentJob: Job = {
      ...queuedJob,
      status: "rendering",
      stage: "device_waiting",
      progress: 78,
      updated_at: 2,
    };
    const liveJob: Job = {
      ...staleRecentJob,
      stage: "device_rendering",
      progress: 82,
      updated_at: 3,
    };
    localStorage.setItem("studio-job:OWN02", liveJob.id);
    api.fetchJobs.mockResolvedValue({ items: [staleRecentJob], total: 1, page: 1, page_size: 4 });
    api.fetchJob.mockResolvedValue({ job: liveJob });

    render(<MemoryRouter initialEntries={["/?workflow=OWN02"]}><StudioPage /></MemoryRouter>);

    await waitFor(() => expect(screen.getAllByText("82%")).toHaveLength(2));
    expect(screen.queryByText("78%")).not.toBeInTheDocument();
    expect(screen.getByText("本机助手正在处理剪映导出")).toBeInTheDocument();
    expect(screen.queryByText("device_rendering")).not.toBeInTheDocument();
  });

  it("opens and saves the selected workflow input settings without navigation", async () => {
    authState.role = "admin";
    render(<MemoryRouter><StudioPage /></MemoryRouter>);
    await screen.findAllByText("已发布");
    fireEvent.click(screen.getByRole("tab", { name: /神话人物/ }));
    fireEvent.click(screen.getByRole("button", { name: "配置神话人物输入参数" }));

    const dialog = await screen.findByRole("dialog", { name: "配置神话人物输入参数" });
    const sceneCount = within(dialog).getByRole("spinbutton", { name: /默认分镜数量/ });
    const voice = within(dialog).getByRole("combobox", { name: /默认配音音色/ });
    expect(sceneCount).toHaveValue(10);
    expect(voice).toHaveDisplayValue("爽快思思 / Skye");
    fireEvent.change(sceneCount, { target: { value: "12" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存并立即生效" }));

    await waitFor(() => expect(api.updateRuntimeSettings).toHaveBeenCalledWith({
      workflow_ids: { OWN01: "11111111", OWN02: "22222222", OWN03: "33333333" },
      workflow_inputs: {
        OWN01: { author: "佚名" },
        OWN02: { left: "未成年人禁止吸烟" },
        OWN03: { shuliang: 12, yinse: "7620288417930297386" },
      },
    }));
    expect(await screen.findByText("神话人物输入参数已保存并立即生效")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
