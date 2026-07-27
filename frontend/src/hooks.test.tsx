import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Job } from "./types";
import { useJobPolling } from "./hooks";

const api = vi.hoisted(() => ({
  fetchJob: vi.fn(),
}));

vi.mock("./api", () => api);

const runningJob: Job = {
  id: "job-1",
  workflow_code: "OWN02",
  category: "自有工作流",
  display_title: "中华",
  status: "running",
  stage: "generating",
  progress: 35,
  results: [],
  created_at: 1,
  updated_at: 2,
};

describe("useJobPolling", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("keeps polling when an active job response has not changed", async () => {
    vi.useFakeTimers();
    const succeededJob: Job = {
      ...runningJob,
      status: "succeeded",
      stage: "completed",
      progress: 100,
      results: [{
        type: "video",
        url: "/api/v1/job-results/job-1-device.mp4",
        poster_url: null,
        downloadable: true,
      }],
      updated_at: 3,
    };
    api.fetchJob
      .mockResolvedValueOnce({ job: { ...runningJob } })
      .mockResolvedValueOnce({ job: succeededJob });

    const { result } = renderHook(() => useJobPolling(runningJob));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(api.fetchJob).toHaveBeenCalledTimes(1);
    expect(result.current.job?.progress).toBe(35);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(api.fetchJob).toHaveBeenCalledTimes(2);
    expect(result.current.job?.status).toBe("succeeded");
    expect(result.current.job?.results[0]?.type).toBe("video");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(api.fetchJob).toHaveBeenCalledTimes(2);
  });
});
