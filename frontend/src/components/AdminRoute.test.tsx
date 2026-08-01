import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AdminRoute } from "./AdminRoute";

const authState = vi.hoisted(() => ({ role: "user" }));

vi.mock("../auth", () => ({
  useAuth: () => ({
    loading: false,
    user: { id: "user-1", role: authState.role },
  }),
}));

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={["/admin/runtime-settings"]}>
      <Routes>
        <Route path="/" element={<div>普通页面</div>} />
        <Route
          path="/admin/runtime-settings"
          element={<AdminRoute><div>管理员设置</div></AdminRoute>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminRoute", () => {
  afterEach(() => cleanup());

  it("redirects a non-admin away from settings", async () => {
    authState.role = "user";
    renderRoute();
    expect(await screen.findByText("普通页面")).toBeInTheDocument();
    expect(screen.queryByText("管理员设置")).not.toBeInTheDocument();
  });

  it("allows the configured admin role", () => {
    authState.role = "admin";
    renderRoute();
    expect(screen.getByText("管理员设置")).toBeInTheDocument();
  });
});
