import { ChevronLeft, ChevronRight, Clock3, Download, FileText, LoaderCircle, Play, RotateCcw, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, fetchJobs, fetchWorkflows, retryJob } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { Job, Workflow } from "../types";

const STATUS_OPTIONS = [
  ["all", "全部状态"],
  ["queued", "等待执行"],
  ["running", "正在生成"],
  ["rendering", "正在渲染"],
  ["succeeded", "生成完成"],
  ["failed", "生成失败"],
] as const;

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "等待执行",
  running: "正在生成",
  rendering: "正在渲染",
  succeeded: "生成完成",
  failed: "生成失败",
};

export function RecordsPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("all");
  const [workflowCode, setWorkflowCode] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [retryingId, setRetryingId] = useState("");
  const [preview, setPreview] = useState<{ jobId: string; url: string; poster?: string | null } | null>(null);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      const result = await fetchJobs({ page, pageSize, status, workflowCode });
      setJobs(result.items);
      setTotal(result.total);
      setError("");
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "login_required") navigate(`/login?redirect=${encodeURIComponent("/records")}`);
      else setError(apiError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/records")}`);
      return;
    }
    void load();
  }, [authLoading, user?.id, page, status, workflowCode]);

  useEffect(() => {
    fetchWorkflows({ category: "全部", q: "", sort: "name" })
      .then(({ items }) => setWorkflows(items))
      .catch(() => setWorkflows([]));
  }, []);

  useEffect(() => {
    if (!jobs.some((job) => !["succeeded", "failed"].includes(job.status))) return;
    const timer = window.setTimeout(() => void load(), 2500);
    return () => window.clearTimeout(timer);
  }, [jobs.map((job) => `${job.id}:${job.updated_at}`).join("|")]);

  const visibleJobs = useMemo(
    () => jobs.filter((job) => !query.trim() || `${job.display_title} ${job.workflow_code}`.toLowerCase().includes(query.trim().toLowerCase())),
    [jobs, query],
  );
  const pages = Math.max(1, Math.ceil(total / pageSize));

  async function retry(job: Job) {
    setRetryingId(job.id);
    setError("");
    try {
      await retryJob(job.id);
      await load();
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "render_device_required") navigate("/devices");
      else if (apiError.code === "password_change_required") navigate("/account/security");
      else setError(apiError.message);
    } finally {
      setRetryingId("");
    }
  }

  return (
    <Layout>
      <main className="content-page page-width records-page">
        <div className="page-heading records-heading">
          <span className="page-icon"><Clock3 /></span>
          <div><h1>创作记录</h1><p>查找、恢复和下载你生成的每一个作品。</p></div>
          <Link className="primary-button heading-action" to="/">开始新创作</Link>
        </div>
        <section className="record-toolbar">
          <label className="search-box"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索主题或工作流编号" /></label>
          <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
            {STATUS_OPTIONS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select>
          <select value={workflowCode} onChange={(event) => { setWorkflowCode(event.target.value); setPage(1); }}>
            <option value="">全部工作流</option>
            {workflows.map((workflow) => <option value={workflow.code} key={`${workflow.category}-${workflow.code}`}>{workflow.code} · {workflow.name}</option>)}
            <option value="DRAFT_KEY_EXPORT">手工剪映导出</option>
          </select>
        </section>
        {error && <div className="notice error">{error}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" />正在加载创作记录</div> : visibleJobs.length ? (
          <div className="record-list">
            {visibleJobs.map((job) => (
              <article className="record-card rich" key={job.id}>
                <div className="record-main">
                  <span className={`record-status ${job.status}`}>{STATUS_TEXT[job.status]}</span>
                  <div>
                    <h3>{job.display_title}</h3>
                    <p>{job.workflow_code} · {job.category} · {new Date(job.created_at * 1000).toLocaleString("zh-CN")}</p>
                  </div>
                  <strong>{job.progress}%</strong>
                </div>
                <div className="record-progress"><i style={{ width: `${job.progress}%` }} /></div>
                {job.error && <div className="record-error">{job.error.message}</div>}
                <div className="record-actions">
                  <span>{job.stage}</span>
                  {job.status === "failed" && (
                    <button type="button" disabled={retryingId === job.id} onClick={() => void retry(job)}>
                      <RotateCcw />{retryingId === job.id ? "重试中" : "重试"}
                    </button>
                  )}
                  {job.results.map((result, index) => (
                    <span className="record-result-actions" key={`${result.url}-${index}`}>
                      {result.type === "video" && (
                        <button
                          type="button"
                          onClick={() => setPreview(
                            preview?.jobId === job.id && preview.url === result.url
                              ? null
                              : { jobId: job.id, url: result.url, poster: result.poster_url },
                          )}
                        >
                          {preview?.jobId === job.id && preview.url === result.url ? <X /> : <Play />}
                          {preview?.jobId === job.id && preview.url === result.url ? "收起视频" : "播放视频"}
                        </button>
                      )}
                      <a href={result.download_url || result.url} target="_blank" rel="noreferrer" download={result.downloadable || undefined}>
                        <Download />下载结果 {index + 1}
                      </a>
                    </span>
                  ))}
                  {job.workflow_code === "DRAFT_KEY_EXPORT"
                    ? <Link to="/jianying-export">打开手工导出</Link>
                    : <Link to={`/?workflow=${job.workflow_code}`}>再次创作</Link>}
                </div>
                {preview?.jobId === job.id && (
                  <div className="record-video-preview">
                    <video
                      key={preview.url}
                      src={preview.url}
                      poster={preview.poster || undefined}
                      controls
                      autoPlay
                      playsInline
                      preload="metadata"
                    />
                  </div>
                )}
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state empty-stack"><FileText /><strong>没有符合条件的创作记录</strong><Link to="/">开始第一个作品</Link></div>
        )}
        {total > pageSize && (
          <nav className="pagination" aria-label="创作记录分页">
            <button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft />上一页</button>
            <span>第 {page} / {pages} 页，共 {total} 条</span>
            <button type="button" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>下一页<ChevronRight /></button>
          </nav>
        )}
      </main>
    </Layout>
  );
}
