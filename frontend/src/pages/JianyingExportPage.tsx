import { FileJson, Laptop, LoaderCircle, Sparkles, UploadCloud } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  ApiError,
  createDraftKeyRender,
  fetchDraftKeyRenderStatus,
  retryJob,
} from "../api";
import { useAuth } from "../auth";
import { JobProgress, Results } from "../components/JobViews";
import { Layout } from "../components/Layout";
import { useJobPolling } from "../hooks";
import type { Job, RenderStatus } from "../types";

export function extractDraftKeyJson(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    const raw = value.trim();
    if (!raw) throw new Error("draft_key JSON 为空");
    try {
      return extractDraftKeyJson(JSON.parse(raw));
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error("不是合法的 JSON 文件");
      throw error;
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("draft_key 必须是 JSON 对象");
  }
  const object = value as Record<string, unknown>;
  if (Array.isArray(object.calls)) return object;
  for (const field of ["draft_key", "key", "key_json", "output", "result", "data", "body"]) {
    const nested = object[field];
    if (nested === undefined || nested === null || nested === "") continue;
    try {
      return extractDraftKeyJson(nested);
    } catch {
      // Continue through common Coze wrappers.
    }
  }
  throw new Error("没有找到包含 calls 数组的 draft_key");
}

const EMPTY_STATUS: RenderStatus = {
  configured: false,
  device_online: false,
  central_configured: false,
  devices: [],
  message: "正在检查剪映导出服务",
};

export function JianyingExportPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [draftText, setDraftText] = useState("");
  const [fileName, setFileName] = useState("");
  const [initialJob, setInitialJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState<RenderStatus>(EMPTY_STATUS);
  const { job, setJob } = useJobPolling(initialJob, setError);

  useEffect(() => {
    fetchDraftKeyRenderStatus()
      .then(setStatus)
      .catch((nextError: Error) => setError(nextError.message));
  }, []);

  async function loadFile(file?: File) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setError("JSON 文件不能超过 5MB");
      return;
    }
    try {
      setDraftText(await file.text());
      setFileName(file.name);
      setError("");
    } catch {
      setError("无法读取所选 JSON 文件");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/jianying-export")}`);
      return;
    }
    if (user.must_change_password) {
      navigate("/account/security");
      return;
    }
    if (!status.configured) {
      navigate("/devices");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await createDraftKeyRender(extractDraftKeyJson(draftText));
      setInitialJob(response.job);
      setJob(response.job);
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "render_device_required") navigate("/devices");
      else if (apiError.code === "password_change_required") navigate("/account/security");
      else setError(apiError.message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!job) return;
    setRetrying(true);
    try {
      const response = await retryJob(job.id);
      setInitialJob(response.job);
      setJob(response.job);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setRetrying(false);
    }
  }

  return (
    <Layout>
      <main className="content-page page-width jianying-export-page">
        <div className="page-heading"><span className="page-icon"><FileJson /></span><div><h1>手工剪映导出</h1><p>为已有 draft_key 提供的高级入口；首页一键生成无需使用这里。</p></div></div>
        <div className={`service-status ${status.configured ? "ready" : "unavailable"}`}>
          <strong>{status.message}</strong>
          <span>{status.configured ? "可以提交草稿并生成 MP4" : "请先在设备中心完成配对"}</span>
          {!status.configured && <Link to="/devices"><Laptop />打开设备中心</Link>}
        </div>
        <div className="jianying-export-layout">
          <section className="generator-panel">
            <div className="section-title"><span>提交 draft_key</span><small>支持标准 JSON 和扣子嵌套输出</small></div>
            <form onSubmit={(event) => void submit(event)}>
              <label className="draft-key-upload"><span><UploadCloud />选择 JSON 文件</span><input type="file" accept=".json,application/json" onChange={(event) => void loadFile(event.target.files?.[0])} /><small>{fileName || "最大 5MB，文件只提交到本站后台"}</small></label>
              <label className="form-field"><span>JSON 内容</span><textarea className="draft-key-textarea" value={draftText} onChange={(event) => { setDraftText(event.target.value); setFileName(""); }} placeholder={'{"kind":"jianying_draft_key","draft":{...},"calls":[...]}'}/></label>
              {error && <div className="notice error">{error}</div>}
              <button className="primary-button" disabled={busy || !draftText.trim()} type="submit">{busy ? <LoaderCircle className="spin" /> : <Sparkles />}{busy ? "正在提交" : status.configured ? "生成剪映视频" : "先连接剪映设备"}</button>
            </form>
          </section>
          <aside className="execution-column">{job ? <JobProgress job={job} onRetry={() => void retry()} retrying={retrying} /> : <div className="execution-placeholder"><strong>自动执行过程</strong><p>校验 JSON → 下载素材 → 创建剪映草稿 → 原生导出 → MP4 回传。</p></div>}</aside>
        </div>
        {job && <Results job={job} />}
      </main>
    </Layout>
  );
}
