import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../types";
import { RecordsPage } from "./RecordsPage";

const api = vi.hoisted(() => ({
  fetchJobs: vi.fn(),
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
      role: "user",
      must_change_password: false,
    },
    loading: false,
  }),
}));

const completedJob: Job = {
  id: "job-video",
  workflow_code: "OWN03",
  category: "自有工作流",
  display_title: "哪吒",
  status: "succeeded",
  stage: "completed",
  progress: 100,
  results: [{
    type: "video",
    url: "/api/v1/job-results/job-video-device.mp4",
    poster_url: null,
    downloadable: true,
  }],
  created_at: 1,
  updated_at: 1,
};

describe("RecordsPage", () => {
  beforeEach(() => {
    api.fetchJobs.mockResolvedValue({
      items: [completedJob],
      total: 1,
      page: 1,
      page_size: 10,
    });
    api.fetchWorkflows.mockResolvedValue({ items: [], total: 0 });
  });

  it("plays and collapses a completed video inside its record card", async () => {
    const { container } = render(<MemoryRouter><RecordsPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "播放视频" }));

    await waitFor(() => {
      expect(container.querySelector("video")).toHaveAttribute(
        "src",
        "/api/v1/job-results/job-video-device.mp4",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "收起视频" }));
    expect(container.querySelector("video")).not.toBeInTheDocument();
  });
});
