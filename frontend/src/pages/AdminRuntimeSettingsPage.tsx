import { Check, KeyRound, LoaderCircle, Save, Settings, SlidersHorizontal, Trash2 } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, fetchRuntimeSettings, updateRuntimeSettings } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { RuntimeSettings, RuntimeWorkflowSetting } from "../types";

function workflowInputValues(workflows: RuntimeWorkflowSetting[]) {
  return Object.fromEntries(workflows.map((item) => [
    item.code,
    {
      ...Object.fromEntries(
        item.input_schema
          .filter((field) => field.default !== undefined)
          .map((field) => [field.name, field.default]),
      ),
      ...(item.input_defaults || {}),
    },
  ]));
}

export function RuntimeSettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedWorkflowCode = (searchParams.get("workflow") || "").trim().toUpperCase();
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [miheKey, setMiheKey] = useState("");
  const [clearMiheKey, setClearMiheKey] = useState(false);
  const [workflowIds, setWorkflowIds] = useState<Record<string, string>>({});
  const [workflowInputs, setWorkflowInputs] = useState<Record<string, Record<string, unknown>>>({});
  const [selectedWorkflowCode, setSelectedWorkflowCode] = useState("");
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
      setWorkflowInputs(workflowInputValues(result.workflows));
      setSelectedWorkflowCode((previous) =>
        result.workflows.some((item) => item.code === requestedWorkflowCode)
          ? requestedWorkflowCode
          : result.workflows.some((item) => item.code === previous)
          ? previous
          : result.workflows[0]?.code || "",
      );
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

  useEffect(() => {
    if (!settings || !requestedWorkflowCode) return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("workflow-inputs")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [settings, requestedWorkflowCode]);

  const visibleWorkflows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return settings?.workflows || [];
    return (settings?.workflows || []).filter((item) =>
      `${item.code} ${item.name} ${item.category}`.toLowerCase().includes(normalized),
    );
  }, [settings?.workflows, query]);

  const selectedWorkflow = useMemo(
    () => settings?.workflows.find((item) => item.code === selectedWorkflowCode) || null,
    [settings?.workflows, selectedWorkflowCode],
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const normalizedWorkflowInputs: Record<string, Record<string, unknown>> = {};
      for (const item of settings?.workflows || []) {
        const values = workflowInputs[item.code] || {};
        const fields = new Map(item.input_schema.map((field) => [field.name, field]));
        const normalized: Record<string, unknown> = {};
        for (const [name, value] of Object.entries(values)) {
          if (value === "" || value === null || value === undefined) continue;
          const field = fields.get(name);
          if (field?.type === "number") {
            const numberValue = typeof value === "number" ? value : Number(value);
            if (!Number.isFinite(numberValue)) {
              throw new Error(`${item.code} 的“${field.label}”必须是数字`);
            }
            normalized[name] = numberValue;
          } else if (!field || !["image", "video", "audio", "file", "notice"].includes(field.type)) {
            normalized[name] = value;
          }
        }
        normalizedWorkflowInputs[item.code] = normalized;
      }
      const result = await updateRuntimeSettings({
        ...(miheKey.trim() ? { mihe_key: miheKey.trim() } : {}),
        ...(clearMiheKey ? { clear_mihe_key: true } : {}),
        workflow_ids: workflowIds,
        workflow_inputs: normalizedWorkflowInputs,
      });
      setSettings(result);
      setWorkflowIds(Object.fromEntries(result.workflows.map((item) => [item.code, item.workflow_id])));
      setWorkflowInputs(workflowInputValues(result.workflows));
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
            <p>集中管理服务器生成服务 Key、工作流 ID 和每个工作流的默认输入参数，仅管理员可访问。</p>
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
                <div><h2>图片生成服务 Key</h2><p>当前状态：{settings.mihe_key.configured ? `已配置 ${settings.mihe_key.masked}` : "未配置"}</p></div>
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
                <span>清除当前图片生成服务 Key</span>
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
                      placeholder="输入工作流 ID"
                    />
                  </label>
                ))}
              </div>
            </section>

            <section className="runtime-workflow-card runtime-input-card" id="workflow-inputs">
              <div className="runtime-card-heading">
                <span><SlidersHorizontal /></span>
                <div>
                  <h2>工作流输入参数</h2>
                  <p>选择工作流后直接修改已有参数，不需要填写参数名或编写 JSON。</p>
                </div>
              </div>

              <label className="runtime-workflow-select">
                <span>选择工作流</span>
                <select
                  value={selectedWorkflowCode}
                  onChange={(event) => setSelectedWorkflowCode(event.target.value)}
                >
                  {(settings.workflows || []).map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.code} · {item.category} · {item.name}
                    </option>
                  ))}
                </select>
              </label>

              {selectedWorkflow ? (
                <div className="runtime-input-editor">
                  <div className="runtime-input-reference">
                    <div>
                      <strong>{selectedWorkflow.code} · {selectedWorkflow.name}</strong>
                      <small>这些参数会作为后台默认值；用户每次运行时填写的非空内容优先。</small>
                    </div>
                    <div className="runtime-input-schema-list">
                      {selectedWorkflow.input_schema.length > 0 ? selectedWorkflow.input_schema.map((field) => (
                        <span key={field.name}>
                          <code>{field.name}</code>
                          {field.label}
                          <em>{field.type}{field.required ? " · 必填" : ""}</em>
                        </span>
                      )) : (
                        <p>这个工作流暂时没有可修改的输入参数。</p>
                      )}
                    </div>
                    <button
                      className="runtime-clear-inputs"
                      type="button"
                      onClick={() => setWorkflowInputs((previous) => ({
                        ...previous,
                        [selectedWorkflow.code]: Object.fromEntries(
                          selectedWorkflow.input_schema.map((field) => [field.name, ""]),
                        ),
                      }))}
                    >
                      <Trash2 />清除这个工作流的后台默认值
                    </button>
                  </div>

                  <div className="runtime-parameter-fields">
                    {selectedWorkflow.input_schema.length > 0 ? selectedWorkflow.input_schema.map((field) => {
                      const value = workflowInputs[selectedWorkflow.code]?.[field.name] ?? "";
                      const setValue = (nextValue: unknown) => setWorkflowInputs((previous) => ({
                        ...previous,
                        [selectedWorkflow.code]: {
                          ...(previous[selectedWorkflow.code] || {}),
                          [field.name]: nextValue,
                        },
                      }));
                      return (
                        <label key={field.name}>
                          <span>
                            <strong>{field.label}</strong>
                            <code>{field.name}</code>
                          </span>
                          {field.type === "select" ? (
                            <select value={String(value)} onChange={(event) => setValue(event.target.value)}>
                              <option value="">不设置后台默认值</option>
                              {(field.options || []).map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          ) : field.type === "textarea" ? (
                            <textarea
                              rows={4}
                              value={String(value)}
                              onChange={(event) => setValue(event.target.value)}
                              placeholder={field.placeholder || "留空表示使用工作流内置值"}
                            />
                          ) : ["image", "video", "audio", "file"].includes(field.type) ? (
                            <div className="runtime-upload-notice">该参数需要在每次运行时选择文件，不能设为固定值。</div>
                          ) : field.type === "notice" ? (
                            <div className="runtime-upload-notice">{String(field.default || "说明参数无需配置")}</div>
                          ) : (
                            <input
                              type={field.type === "number" ? "number" : "text"}
                              min={field.min}
                              max={field.max}
                              value={String(value)}
                              onChange={(event) => setValue(event.target.value)}
                              placeholder={field.placeholder || "留空表示使用工作流内置值"}
                            />
                          )}
                        </label>
                      );
                    }) : (
                      <div className="runtime-upload-notice">这个工作流暂时没有可修改的输入参数。</div>
                    )}
                    <small className="runtime-parameter-hint">
                      密钥类配置仍在上方独立管理；上传素材继续在每次运行工作流时选择。
                    </small>
                  </div>
                </div>
              ) : null}
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
