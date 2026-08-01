import { Check, LoaderCircle, Save, Settings, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError, fetchRuntimeSettings, updateRuntimeSettings } from "../api";
import type { InputField, RuntimeSettings, RuntimeWorkflowSetting } from "../types";

type Props = {
  workflowCode: string;
  workflowLabel: string;
  onClose: () => void;
  onSaved: () => void;
};

function workflowValues(workflow: RuntimeWorkflowSetting) {
  return {
    ...Object.fromEntries(
      workflow.input_schema
        .filter((field) => field.default !== undefined)
        .map((field) => [field.name, field.default]),
    ),
    ...(workflow.input_defaults || {}),
  };
}

function normalizeValue(field: InputField, value: unknown) {
  if (value === "" || value === null || value === undefined) return undefined;
  if (field.type !== "number") return value;
  const numberValue = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numberValue)) throw new Error(`“${field.label}”必须是数字`);
  if (field.min !== undefined && numberValue < field.min) {
    throw new Error(`“${field.label}”不能小于 ${field.min}`);
  }
  if (field.max !== undefined && numberValue > field.max) {
    throw new Error(`“${field.label}”不能大于 ${field.max}`);
  }
  return numberValue;
}

export function WorkflowInputSettingsDialog({ workflowCode, workflowLabel, onClose, onSaved }: Props) {
  const [settings, setSettings] = useState<RuntimeSettings | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const workflow = useMemo(
    () => settings?.workflows.find((item) => item.code === workflowCode) || null,
    [settings, workflowCode],
  );

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);

    fetchRuntimeSettings()
      .then((result) => {
        const selected = result.workflows.find((item) => item.code === workflowCode);
        setSettings(result);
        setValues(selected ? workflowValues(selected) : {});
        setError(selected ? "" : "没有找到这个工作流的输入参数配置");
      })
      .catch((nextError: Error) => setError((nextError as ApiError).message))
      .finally(() => setLoading(false));

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [workflowCode]);

  function setValue(name: string, value: unknown) {
    setValues((previous) => ({ ...previous, [name]: value }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings || !workflow) return;
    setSaving(true);
    setError("");
    try {
      const currentInputs: Record<string, unknown> = {};
      for (const field of workflow.input_schema) {
        if (["image", "video", "audio", "file", "notice"].includes(field.type)) continue;
        const normalized = normalizeValue(field, values[field.name]);
        if (normalized !== undefined) currentInputs[field.name] = normalized;
      }
      await updateRuntimeSettings({
        workflow_ids: Object.fromEntries(settings.workflows.map((item) => [item.code, item.workflow_id])),
        workflow_inputs: Object.fromEntries(settings.workflows.map((item) => [
          item.code,
          item.code === workflowCode ? currentInputs : (item.input_defaults || {}),
        ])),
      });
      onSaved();
    } catch (nextError) {
      setError((nextError as ApiError).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="workflow-input-modal-backdrop" onMouseDown={onClose}>
      <section
        className="workflow-input-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workflow-input-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <span><Settings /></span>
          <div>
            <h2 id="workflow-input-modal-title">配置{workflowLabel}输入参数</h2>
            <p>保存后立即用于下一次生成，不会改变其他工作流。</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭配置弹窗"><X /></button>
        </header>

        {loading ? (
          <div className="workflow-input-modal-loading"><LoaderCircle className="spin" />正在读取当前配置</div>
        ) : (
          <form onSubmit={(event) => void save(event)}>
            {error && <div className="notice error" role="alert">{error}</div>}
            {workflow?.input_schema.length ? (
              <div className="workflow-input-modal-fields">
                {workflow.input_schema.map((field) => {
                  const value = values[field.name] ?? "";
                  return (
                    <label key={field.name}>
                      <span><strong>{field.label}</strong><code>{field.name}</code></span>
                      {field.type === "select" ? (
                        <select value={String(value)} onChange={(event) => setValue(field.name, event.target.value)}>
                          <option value="">使用工作流内置值</option>
                          {(field.options || []).map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                      ) : field.type === "textarea" ? (
                        <textarea
                          rows={4}
                          value={String(value)}
                          onChange={(event) => setValue(field.name, event.target.value)}
                          placeholder={field.placeholder || "留空时使用工作流内置值"}
                        />
                      ) : ["image", "video", "audio", "file"].includes(field.type) ? (
                        <div className="workflow-input-modal-note">该素材需要在每次运行时选择，不能设为固定值。</div>
                      ) : field.type === "notice" ? (
                        <div className="workflow-input-modal-note">{String(field.default || "该说明参数无需配置")}</div>
                      ) : (
                        <input
                          type={field.type === "number" ? "number" : "text"}
                          min={field.min}
                          max={field.max}
                          value={String(value)}
                          onChange={(event) => setValue(field.name, event.target.value)}
                          placeholder={field.placeholder || "留空时使用工作流内置值"}
                        />
                      )}
                    </label>
                  );
                })}
              </div>
            ) : !error ? (
              <div className="workflow-input-modal-empty"><Check />这个工作流暂时没有其他可配置参数</div>
            ) : null}
            <footer>
              <button className="secondary-button" type="button" onClick={onClose}>取消</button>
              <button className="primary-button" type="submit" disabled={saving || !workflow}>
                {saving ? <LoaderCircle className="spin" /> : <Save />}
                {saving ? "正在保存" : "保存并立即生效"}
              </button>
            </footer>
          </form>
        )}
      </section>
    </div>
  );
}
