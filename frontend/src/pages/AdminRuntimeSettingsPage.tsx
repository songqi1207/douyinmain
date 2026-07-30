import { Check, KeyRound, LoaderCircle, Save, Settings } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, fetchRuntimeSettings, updateRuntimeSettings } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { RuntimeSettings } from "../types";

export function RuntimeSettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [miheKey, setMiheKey] = useState("");
  const [clearMiheKey, setClearMiheKey] = useState(false);
  const [workflowIds, setWorkflowIds] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true);
    try {
      const result = await fetchRuntimeSettings();
      setSettings(result);
      setWorkflowIds(Object.fromEntries(result.workflows.map((item) => [item.code, item.workflow_id])));
      setError("");
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "login_required") navigate("/login?redirect=/admin/runtime-settings");
      else setError(apiError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate("/login?redirect=/admin/runtime-settings");
      return;
    }
    if (user.role !== "admin") {
      setError("只有管理员可以修改运行配置");
      setLoading(false);
      return;
    }
    void load();
  }, [authLoading, user?.id, user?.role]);

  const visibleWorkflows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return settings?.workflows || [];
    return (settings?.workflows || []).filter((item) =>
      `${item.code} ${item.name} ${item.category}`.toLowerCase().includes(normalized),
    );
  }, [settings?.workflows, query]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await updateRuntimeSettings({
        ...(miheKey.trim() ? { mihe_key: miheKey.trim() } : {}),
        ...(clearMiheKey ? { clear_mihe_key: true } : {}),
        workflow_ids: workflowIds,
      });
      setSettings(result);
      setWorkflowIds(Object.fromEntries(result.workflows.map((item) => [item.code, item.workflow_id])));
      setMiheKey("");
      setClearMiheKey(false);
      setMessage(result.message || "运行配置已保存");
    } catch (nextError) {
      setError((nextError as ApiError).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Layout>
      <main className="content-page page-width runtime-settings-page">
        <div className="page-heading">
          <span className="page-icon"><Settings /></span>
          <div>
            <h1>运行配置</h1>
            <p>集中管理服务器米核 Key 与 Coze 工作流 ID，仅管理员可访问。</p>
          </div>
        </div>

        {error && <div className="notice error" role="alert">{error}</div>}
        {message && <div className="notice success"><Check />{message}</div>}

        {loading ? (
          <div className="loading-state"><LoaderCircle className="spin" />正在读取服务器配置</div>
        ) : settings ? (
          <form className="runtime-settings-form" onSubmit={(event) => void save(event)}>
            <section className="runtime-secret-card">
              <div className="runtime-card-heading">
                <span><KeyRound /></span>
                <div><h2>米核 Key</h2><p>当前状态：{settings.mihe_key.configured ? `已配置 ${settings.mihe_key.masked}` : "未配置"}</p></div>
              </div>
              <label>
                <span>替换为新 Key</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={miheKey}
                  disabled={clearMiheKey}
                  onChange={(event) => setMiheKey(event.target.value)}
                  placeholder="留空表示保持当前 Key 不变"
                />
                <small>服务器不会把 Key 明文返回浏览器；保存后只显示末四位。</small>
              </label>
              <label className="runtime-checkbox">
                <input
                  type="checkbox"
                  checked={clearMiheKey}
                  onChange={(event) => setClearMiheKey(event.target.checked)}
                />
                <span>清除当前米核 Key</span>
              </label>
            </section>

            <section className="runtime-workflow-card">
              <div className="runtime-card-heading">
                <span><Settings /></span>
                <div><h2>工作流 ID</h2><p>保存后立即用于下一次任务，不需要重启服务。</p></div>
              </div>
              <input
                className="runtime-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索工作流编号、名称或分类"
              />
              <div className="runtime-workflow-grid">
                {visibleWorkflows.map((item) => (
                  <label key={item.code}>
                    <span><strong>{item.code}</strong><small>{item.category} · {item.name}</small></span>
                    <input
                      inputMode="numeric"
                      value={workflowIds[item.code] || ""}
                      onChange={(event) => setWorkflowIds((previous) => ({
                        ...previous,
                        [item.code]: event.target.value.replace(/\D/g, ""),
                      }))}
                      placeholder="输入 Coze 工作流 ID"
                    />
                  </label>
                ))}
              </div>
            </section>

            <div className="runtime-save-bar">
              <span>共 {settings.workflows.length} 个工作流配置项</span>
              <button className="primary-button" disabled={saving} type="submit">
                {saving ? <LoaderCircle className="spin" /> : <Save />}
                {saving ? "正在保存" : "保存并立即生效"}
              </button>
            </div>
          </form>
        ) : null}
      </main>
    </Layout>
  );
}
