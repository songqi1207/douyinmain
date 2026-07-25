import { describe, expect, it } from "vitest";

import { extractDraftKeyJson } from "./JianyingExportPage";

describe("extractDraftKeyJson", () => {
  it("accepts nested Coze output", () => {
    const key = { kind: "jianying_draft_key", calls: [{ tool: "add_images" }] };
    expect(extractDraftKeyJson({ output: JSON.stringify({ draft_key: JSON.stringify(key) }) })).toEqual(key);
  });

  it("rejects objects without recorded calls", () => {
    expect(() => extractDraftKeyJson({ draft: {} })).toThrow("没有找到");
  });
});
