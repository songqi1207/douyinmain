import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminJob } from "../types";
import { AdminCreationsPage } from "./AdminCreationsPage";

const api = vi.hoisted(() => ({
  fetchAdminJobs: vi.fn(),
  fetchWorkflows: vi.fn(),
  fetchAccountQuota: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return { ...original, ...api };
});

vi.mock("../auth", () => ({
  useAuth: () => ({
    user: { id: "admin-1", username: "admin", email: "admin@example.test", role: "admin" },
    loading: false,
    logout: vi.fn(),
  }),
}));

const job: AdminJob = {
  id: "job-12345678",
  workflow_code: "OWN03",
  category: "自有工作流",
  display_title: "财神赵公明",
  status: "succeeded",
  stage: "completed",
  progress: 100,
  price_points: 100,
  results: [{ type: "video", url: "/api/v1/job-results/cai-shen.mp4", downloadable: true }],
  error: null,
  created_at: 1,
  updated_at: 1,
  user: { id: "user-1", username: "creator01", email: "creator@example.test", role: "user", active: true },
};

describe("AdminCreationsPage", () => {
  beforeEach(() => {
    api.fetchAdminJobs.mockResolvedValue({
      items: [job],
      users: [job.user],
      summary: { total: 1, users: 1, succeeded: 1, failed: 0, active: 0, points: 100 },
      total: 1,
      page: 1,
      page_size: 20,
    });
    api.fetchWorkflows.mockResolvedValue({ items: [], total: 0 });
    api.fetchAccountQuota.mockRejectedValue(new Error("not needed"));
  });

  it("shows who created each job and lets the administrator preview its video", async () => {
    const { container } = render(<MemoryRouter><AdminCreationsPage /></MemoryRouter>);

    expect((await screen.findAllByText("creator@example.test")).length).toBeGreaterThanOrEqual(1);
    expect(container).toHaveTextContent("财神赵公明");
    expect(container).toHaveTextContent("积分");
    expect(container).toHaveTextContent("100");

    fireEvent.click(screen.getByRole("button", { name: "播放视频" }));
    await waitFor(() => expect(container.querySelector("video")).toHaveAttribute("src", "/api/v1/job-results/cai-shen.mp4"));
  });
});
