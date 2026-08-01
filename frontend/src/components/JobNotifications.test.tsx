import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../types";
import { JobNotifications } from "./JobNotifications";

const api = vi.hoisted(() => ({ fetchJobs: vi.fn() }));

vi.mock("../api", () => api);
vi.mock("../auth", () => ({
  useAuth: () => ({ user: { id: "user-1", email: "creator@example.test" } }),
}));

const running: Job = {
  id: "job-1",
  workflow_code: "OWN01",
  category: "自有工作流",
  display_title: "活着",
  status: "rendering",
  stage: "rendering",
  progress: 80,
  results: [],
  created_at: 1,
  updated_at: 2,
};

describe("JobNotifications", () => {
  const notification = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    localStorage.setItem("job-notifications-enabled", "true");
    Object.assign(notification, { permission: "granted", requestPermission: vi.fn() });
    vi.stubGlobal("Notification", notification);
    api.fetchJobs
      .mockResolvedValueOnce({ items: [running], total: 1, page: 1, page_size: 50 })
      .mockResolvedValueOnce({
        items: [{ ...running, status: "succeeded", stage: "completed", progress: 100 }],
        total: 1,
        page: 1,
        page_size: 50,
      });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("notifies once when an active job completes", async () => {
    render(<JobNotifications />);
    await act(async () => { await Promise.resolve(); });
    expect(api.fetchJobs).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });

    expect(screen.getByText("视频已生成完成")).toBeInTheDocument();
    expect(screen.getByText(/活着 已完成/)).toBeInTheDocument();
    expect(notification).toHaveBeenCalledTimes(1);
    expect(notification).toHaveBeenCalledWith("视频已生成完成", expect.objectContaining({ tag: "workflow-job-job-1" }));
  });

  it("lets the user disable notifications", () => {
    render(<JobNotifications />);
    fireEvent.click(screen.getByRole("button", { name: "关闭任务通知" }));
    expect(localStorage.getItem("job-notifications-enabled")).toBe("false");
    expect(screen.getByRole("button", { name: "开启任务通知" })).toBeInTheDocument();
  });
});
