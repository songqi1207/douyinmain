import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchJobs, fetchMe } from "./api";

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("preserves structured backend error codes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        detail: {
          code: "password_change_required",
          message: "请先修改临时密码",
        },
      }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    )));

    await expect(fetchMe()).rejects.toMatchObject({
      code: "password_change_required",
      status: 403,
      message: "请先修改临时密码",
    });
  });

  it("serializes job filters without leaking unrelated values", async () => {
    const request = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ items: [], total: 0, page: 2, page_size: 10 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", request);

    await fetchJobs({
      page: 2,
      pageSize: 10,
      status: "failed",
      workflowCode: "own01",
    });

    const url = String(request.mock.calls[0][0]);
    expect(url).toContain("page=2");
    expect(url).toContain("page_size=10");
    expect(url).toContain("status=failed");
    expect(url).toContain("workflow_code=own01");
  });
});
