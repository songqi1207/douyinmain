import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path.endsWith("/auth/me")) {
      body = { user: null, workflow_favorites: [], voice_favorites: [] };
    } else if (path.endsWith("/workflows")) {
      body = { items: [], total: 0 };
    } else if (path.endsWith("/draft-key-renders/status")) {
      body = {
        configured: false,
        device_online: false,
        central_configured: false,
        devices: [],
        message: "请先配对设备",
      };
    } else if (path.endsWith("/site-summary")) {
      body = {
        catalog: { workflows: 3, online_workflows: 3, categories: 1, voices: 0 },
        activity: { users: 0, favorites: 0, views: 0, downloads: 0, runs: 0 },
        jobs: { total: 0, succeeded: 0, active: 0, failed: 0 },
        voice_service: { provider: "", available: false, message: "" },
      };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
});

test("首页与登录页可访问", async ({ page }) => {
  await page.goto("./");
  await expect(page.locator(".app-shell")).toBeVisible();
  await expect(page.locator(".studio-page")).toBeVisible();

  await page.goto("./login");
  await expect(page.locator(".auth-card")).toBeVisible();
  await expect(page.locator('input[type="password"]')).toBeVisible();
});

test("受保护页面会引导登录", async ({ page }) => {
  await page.goto("./devices");
  await expect(page).toHaveURL(/\/business\/login\?redirect=/);

  await page.goto("./records");
  await expect(page).toHaveURL(/\/business\/login\?redirect=/);
});

test("390px 下可通过菜单访问主要页面", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("mobile"), "仅检查移动布局");
  await page.goto("./");

  const menuButton = page.locator(".mobile-menu-button");
  await expect(menuButton).toBeVisible();
  await menuButton.click();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".topnav")).toHaveClass(/open/);
  await page.locator('.topnav a[href="/business/workflows"]').click();
  await expect(page).toHaveURL(/\/business\/workflows$/);
});
