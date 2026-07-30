import { Braces, Check, KeyRound, LoaderCircle, Save, Settings } from "lucide-react";
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
  const [workflowInputJson, setWorkflowInputJson] = useState<Record<string, string>>({});
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
      setWorkflowInputJson(Object.fromEntries(
        result.workflows.map((item) => [
          item.code,
          JSON.stringify(item.input_defaults || {}, null, 2),
        ]),
      ));
      setSelectedWorkflowCode((previous) =>
        result.workflows.some((item) => item.code === previous)
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
      const workflowInputs: Record<string, Record<string, unknown>> = {};
      for (const item of settings?.workflows || []) {
        const raw = (workflowInputJson[item.code] || "{}").trim() || "{}";
        let parsed: unknown;
        try {
          parsed = JSON.parse(raw);
        } catch {
          throw new Error(`${item.code} 的输入参数不是合法 JSON`);
        }
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error(`${item.code} 的输入参数必须是 JSON 对象`);
        }
        workflowInputs[item.code] = parsed as Record<string, unknown>;
      }
      const result = await updateRuntimeSettings({
        ...(miheKey.trim() ? { mihe_key: miheKey.trim() } : {}),
        ...(clearMiheKey ? { clear_mihe_key: true } : {}),
        workflow_ids: workflowIds,
        workflow_inputs: workflowInputs,
      });
      setSettings(result);
      setWorkflowIds(Object.fromEntries(result.workflows.map((item) => [item.code, item.workflow_id])));
      setWorkflowInputJson(Object.fromEntries(
        result.workflows.map((item) => [
          item.code,
          JSON.stringify(item.input_defaults || {}, null, 2),
        ]),
      ));
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
            <p>集中管理服务器米核 Key、Coze 工作流 ID 和每个工作流的默认输入参数，仅管理员可访问。</p>
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

            <section className="runtime-workflow-card runtime-input-card">
              <div className="runtime-card-heading">
                <span><Braces /></span>
                <div>
                  <h2>工作流输入参数</h2>
                  <p>选择工作流后编辑默认参数；用户运行时填写的非空值会优先覆盖这里的配置。</p>
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
                      <strong>{selectedWorkflow.code} 可用页面参数</strong>
                      <small>下面是网站已经识别的字段；也可以在 JSON 中填写该 Coze 工作流支持的其他参数。</small>
                    </div>
                    <div className="runtime-input-schema-list">
                      {selectedWorkflow.input_schema.length > 0 ? selectedWorkflow.input_schema.map((field) => (
                        <span key={field.name}>
                          <code>{field.name}</code>
                          {field.label}
                          <em>{field.type}{field.required ? " · 必填" : ""}</em>
                        </span>
                      )) : (
                        <p>该工作流没有公开页面字段，请直接按 Coze 开始节点的参数名填写。</p>
                      )}
                    </div>
                  </div>

                  <label className="runtime-json-editor">
                    <span>默认输入参数（JSON 对象）</span>
                    <textarea
                      rows={12}
                      spellCheck={false}
                      value={workflowInputJson[selectedWorkflow.code] || "{}"}
                      onChange={(event) => setWorkflowInputJson((previous) => ({
                        ...previous,
                        [selectedWorkflow.code]: event.target.value,
                      }))}
                      placeholder={'{\n  "scene_count": 12,\n  "voice_id": "你的音色 ID"\n}'}
                    />
                    <small>
                      支持文字、数字、布尔值、数组和对象。上传图片、视频、音频、文件仍应在每次运行时选择；
                      API Key、Token、密码等密钥参数不会在这里保存。
                    </small>
                  </label>
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
