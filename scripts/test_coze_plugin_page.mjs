#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { chromium } from "playwright";

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const raw = argv[i];
    if (!raw.startsWith("--")) continue;
    const key = raw.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = "true";
      continue;
    }
    args[key] = next;
    i += 1;
  }
  return args;
}

function usage() {
  return [
    "Usage:",
    "  npm run test:coze-plugin -- --url <plugin-page-url> --tool <tool_name> --payload-file <json>",
    "",
    "Options:",
    "  --url           Coze plugin or tool debug page URL",
    "  --tool          Tool name, for example add_images",
    "  --payload-file  JSON file path",
    "  --payload-json  Inline JSON string",
    "  --headless      true/false, default false",
    "  --timeout-ms    action timeout, default 20000",
    "  --wait-login    true/false, default true",
    "",
    "Example:",
    "  npm run test:coze-plugin -- --url \"https://www.coze.cn/space/.../plugin/...\" --tool add_images --payload-file docs/coze_add_images_payload.sample.json",
  ].join("\n");
}

function boolArg(value, fallback = false) {
  if (value == null) return fallback;
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
}

async function readPayload(args) {
  if (args["payload-json"]) {
    return JSON.parse(args["payload-json"]);
  }
  if (args["payload-file"]) {
    const raw = await fs.readFile(path.resolve(args["payload-file"]), "utf-8");
    return JSON.parse(raw);
  }
  throw new Error("missing --payload-file or --payload-json");
}

function flattenPayload(value, state = { seen: new Map(), items: [] }, pathParts = []) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => flattenPayload(item, state, [...pathParts, `[${index}]`]));
    return state;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      flattenPayload(item, state, [...pathParts, key]);
    }
    return state;
  }

  const key = [...pathParts].reverse().find((part) => !part.startsWith("[")) || "";
  if (!key) return state;

  const occurrence = state.seen.get(key) || 0;
  state.seen.set(key, occurrence + 1);
  state.items.push({
    key,
    occurrence,
    path: pathParts.join(".").replace(".[", "["),
    value,
  });
  return state;
}

async function promptEnter(message) {
  const rl = readline.createInterface({ input, output });
  try {
    await rl.question(`${message}\nPress Enter to continue...`);
  } finally {
    rl.close();
  }
}

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function clickFirstVisible(page, labels) {
  for (const label of labels) {
    const variants = [
      page.getByRole("button", { name: label, exact: true }),
      page.getByRole("link", { name: label, exact: true }),
      page.getByText(label, { exact: true }),
      page.getByText(label),
    ];
    for (const locator of variants) {
      const count = await locator.count().catch(() => 0);
      for (let index = 0; index < count; index += 1) {
        const item = locator.nth(index);
        if (await item.isVisible().catch(() => false)) {
          await item.click({ timeout: 3000 }).catch(() => null);
          return true;
        }
      }
    }
  }
  return false;
}

async function fillField(page, field) {
  const result = await page.evaluate(({ label, value, occurrence }) => {
    const normalize = (text) => String(text || "").replace(/\s+/g, " ").trim();
    const isVisible = (element) => {
      if (!(element instanceof HTMLElement)) return false;
      const style = window.getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden") return false;
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };

    const isEditable = (element) => {
      if (!(element instanceof HTMLElement)) return false;
      if (!isVisible(element)) return false;
      if (element.hasAttribute("disabled")) return false;
      if (element.getAttribute("aria-disabled") === "true") return false;
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        return !element.readOnly && element.type !== "hidden";
      }
      return element.getAttribute("contenteditable") === "true" || element.getAttribute("role") === "textbox";
    };

    const setValue = (element, nextValue) => {
      const stringValue = String(nextValue ?? "");
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        element.focus();
        element.value = "";
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.value = stringValue;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        element.blur();
        return true;
      }
      if (element instanceof HTMLElement) {
        element.focus();
        element.textContent = stringValue;
        element.dispatchEvent(new InputEvent("input", { bubbles: true, data: stringValue, inputType: "insertText" }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        element.blur();
        return true;
      }
      return false;
    };

    const labels = Array.from(document.querySelectorAll("body *")).filter((element) => {
      if (!(element instanceof HTMLElement)) return false;
      if (!isVisible(element)) return false;
      if (element.children.length > 8) return false;
      return normalize(element.innerText || element.textContent) === label;
    });

    const roots = [];
    for (const labelEl of labels) {
      let current = labelEl;
      for (let depth = 0; depth < 7 && current; depth += 1) {
        const inputs = Array.from(
          current.querySelectorAll('input, textarea, [contenteditable="true"], [role="textbox"]'),
        ).filter(isEditable);
        if (inputs.length > 0) {
          roots.push({
            root: current,
            inputs,
            score: current.querySelectorAll("*").length,
          });
        }
        current = current.parentElement;
      }
    }

    const unique = [];
    for (const item of roots.sort((a, b) => a.score - b.score)) {
      if (!unique.some((entry) => entry.root === item.root)) {
        unique.push(item);
      }
    }

    const target = unique[occurrence] || unique[0];
    if (!target) {
      return { ok: false, reason: `label not found: ${label}` };
    }

    const editable = target.inputs.find(isEditable) || target.inputs[0];
    const ok = setValue(editable, value);
    return ok
      ? { ok: true }
      : { ok: false, reason: `unable to set value for label: ${label}` };
  }, field);

  if (!result?.ok) {
    throw new Error(`${field.path}: ${result?.reason || "fill failed"}`);
  }
}

async function openToolIfNeeded(page, toolName) {
  if (!toolName) return;
  const currentText = await page.locator("body").innerText().catch(() => "");
  if (currentText.includes(`${toolName} 输入参数`) || currentText.includes(`.${toolName}`)) {
    return;
  }

  const clicked = await clickFirstVisible(page, [
    `.${toolName}`,
    toolName,
    `抖音工作流辅助工具.${toolName}`,
  ]);

  if (!clicked) {
    throw new Error(`tool not found on page: ${toolName}`);
  }
}

async function waitForDebugPanel(page, timeoutMs) {
  await page.waitForLoadState("domcontentloaded", { timeout: timeoutMs }).catch(() => null);
  await page.waitForTimeout(1200);
  const bodyText = await page.locator("body").innerText().catch(() => "");
  if (!bodyText.includes("输入参数") && !bodyText.includes("Request")) {
    throw new Error("debug panel not ready");
  }
}

async function runDebug(page, timeoutMs) {
  const clicked = await clickFirstVisible(page, ["运行", "调试", "Debug"]);
  if (!clicked) {
    throw new Error("run button not found");
  }

  await page.waitForTimeout(2500);
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const bodyText = await page.locator("body").innerText().catch(() => "");
    if (
      bodyText.includes("调试通过") ||
      bodyText.includes("Response") ||
      bodyText.includes("原因说明") ||
      bodyText.includes("Raw Response")
    ) {
      return;
    }
    await page.waitForTimeout(800);
  }
}

async function extractResponse(page) {
  await clickFirstVisible(page, ["Response", "响应"]);
  await page.waitForTimeout(800);
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const markers = ["Response", "原因说明", "Raw Response", "调试通过"];
  const snippets = [];
  for (const marker of markers) {
    const index = bodyText.indexOf(marker);
    if (index >= 0) {
      snippets.push(bodyText.slice(index, index + 3000));
    }
  }
  return snippets.join("\n\n----\n\n") || bodyText.slice(0, 4000);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.url || (!args.tool && !args["tool-name"])) {
    console.error(usage());
    process.exit(1);
  }

  const toolName = args.tool || args["tool-name"];
  const payload = await readPayload(args);
  const timeoutMs = Number(args["timeout-ms"] || 20000);
  const headless = boolArg(args.headless, false);
  const waitLogin = boolArg(args["wait-login"], true);
  const now = new Date().toISOString().replace(/[:.]/g, "-");
  const outputDir = path.resolve("temp", "coze_ui_test", now);
  const userDataDir = path.resolve("temp", "coze_ui_test", "profile");
  await ensureDir(outputDir);
  await ensureDir(userDataDir);

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless,
    viewport: { width: 1600, height: 1100 },
  });

  let page = context.pages()[0];
  if (!page) {
    page = await context.newPage();
  }

  page.setDefaultTimeout(timeoutMs);

  try {
    await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    await page.waitForTimeout(1500);

    const firstText = await page.locator("body").innerText().catch(() => "");
    const needLogin =
      firstText.includes("登录") ||
      firstText.includes("手机号登录") ||
      firstText.includes("扫码登录") ||
      page.url().includes("/login");
    if (needLogin && waitLogin) {
      await promptEnter("Coze page needs login. Complete login in the opened browser window first.");
      await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
      await page.waitForTimeout(1200);
    }

    await openToolIfNeeded(page, toolName);
    await waitForDebugPanel(page, timeoutMs);
    await page.screenshot({ path: path.join(outputDir, "before-fill.png"), fullPage: true });

    const fields = flattenPayload(payload).items;
    for (const field of fields) {
      await fillField(page, field);
      await page.waitForTimeout(150);
    }

    await page.screenshot({ path: path.join(outputDir, "after-fill.png"), fullPage: true });
    await runDebug(page, timeoutMs);
    await page.screenshot({ path: path.join(outputDir, "after-run.png"), fullPage: true });

    const responseText = await extractResponse(page);
    const summary = {
      ok: true,
      url: page.url(),
      tool: toolName,
      output_dir: outputDir,
      response_text: responseText,
    };
    await fs.writeFile(path.join(outputDir, "result.json"), JSON.stringify(summary, null, 2), "utf-8");
    console.log(JSON.stringify(summary, null, 2));
  } catch (error) {
    const failure = {
      ok: false,
      tool: toolName,
      output_dir: outputDir,
      error: String(error?.message || error),
      url: page.url(),
    };
    await page.screenshot({ path: path.join(outputDir, "failure.png"), fullPage: true }).catch(() => null);
    await fs.writeFile(path.join(outputDir, "result.json"), JSON.stringify(failure, null, 2), "utf-8");
    console.error(JSON.stringify(failure, null, 2));
    process.exitCode = 1;
  } finally {
    await context.close().catch(() => null);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
