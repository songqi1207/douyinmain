import { describe, expect, it } from "vitest";

import { buildSampleDraftKey, extractDraftKeyJson } from "./JianyingExportPage";

describe("extractDraftKeyJson", () => {
  it("accepts nested Coze output", () => {
    const key = { kind: "jianying_draft_key", calls: [{ tool: "add_images" }] };
    expect(extractDraftKeyJson({ output: JSON.stringify({ draft_key: JSON.stringify(key) }) })).toEqual(key);
  });

  it("rejects objects without recorded calls", () => {
    expect(() => extractDraftKeyJson({ draft: {} })).toThrow("没有找到");
  });

  it("builds a minimal export smoke-test draft key", () => {
    const key = buildSampleDraftKey();
    expect(key.kind).toBe("jianying_draft_key");
    expect(key.draft.width).toBe(1080);
    expect(key.calls[0].tool).toBe("add_captions");
    expect(extractDraftKeyJson(key)).toEqual(key);
  });
});
