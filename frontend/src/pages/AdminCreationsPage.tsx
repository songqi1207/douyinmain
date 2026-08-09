import { ChevronLeft, ChevronRight, CircleDollarSign, Clock3, Download, FileText, LoaderCircle, Play, RefreshCw, Search, Trash2, UsersRound, Video, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { ApiError, clearAdminJobQueue, fetchAdminJobs, fetchWorkflows, retryAdminJob } from "../api";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";
import type { AdminJob, AdminJobPage, Workflow } from "../types";

const STATUS_OPTIONS = [
  ["all", "全部状态", "All statuses"],
  ["queued", "等待执行", "Queued"],
  ["running", "正在生成", "Generating"],
  ["rendering", "正在渲染", "Rendering"],
  ["succeeded", "生成完成", "Completed"],
  ["failed", "生成失败", "Failed"],
] as const;

const STATUS_TEXT: Record<AdminJob["status"], [string, string]> = {
  queued: ["等待执行", "Queued"],
  running: ["正在生成", "Generating"],
  rendering: ["正在渲染", "Rendering"],
  succeeded: ["生成完成", "Completed"],
  failed: ["生成失败", "Failed"],
};

const EMPTY_SUMMARY: AdminJobPage["summary"] = {
  total: 0,
  users: 0,
  succeeded: 0,
  failed: 0,
  active: 0,
  points: 0,
};

export function AdminCreationsPage() {
  const { tr, locale } = usePreferences();
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [users, setUsers] = useState<AdminJob["user"][]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("all");
  const [workflowCode, setWorkflowCode] = useState("");
  const [userId, setUserId] = useState("");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<{ jobId: string; url: string; poster?: string | null } | null>(null);
  const [retryingId, setRetryingId] = useState("");
  const [clearingQueue, setClearingQueue] = useState(false);
  const [queueMessage, setQueueMessage] = useState("");

  async function load() {
    setLoading(true);
    try {
      const result = await fetchAdminJobs({ page, pageSize, status, workflowCode, userId, q: query });
      setJobs(result.items);
      setUsers(result.users);
      setSummary(result.summary);
      setTotal(result.total);
      setError("");
    } catch (nextError) {
      setError((nextError as ApiError).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [page, status, workflowCode, userId, query]);

  useEffect(() => {
    fetchWorkflows({ category: "全部", q: "", sort: "name" })
      .then(({ items }) => setWorkflows(items))
      .catch(() => setWorkflows([]));
  }, []);

  useEffect(() => {
    if (!jobs.some((job) => !["succeeded", "failed"].includes(job.status))) return;
    const timer = window.setTimeout(() => void load(), 3000);
    return () => window.clearTimeout(timer);
  }, [jobs.map((job) => `${job.id}:${job.updated_at}`).join("|")]);

  function search(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setQuery(queryInput.trim());
  }

  async function retry(job: AdminJob) {
    setRetryingId(job.id);
    try {
      await retryAdminJob(job.id);
      await load();
    } catch (nextError) {
      setError((nextError as ApiError).message);
    } finally {
      setRetryingId("");
    }
  }

  async function clearQueue() {
    if (summary.active <= 0 || clearingQueue) return;
    const confirmed = window.confirm(tr(
      `确定清空当前 ${summary.active} 个活动任务吗？排队、生成中和剪映导出中的任务会被删除，冻结积分会退回；已完成作品不受影响。`,
      `Clear all ${summary.active} active jobs? Queued, generating and rendering jobs will be deleted and frozen credits refunded. Completed work is kept.`,
    ));
    if (!confirmed) return;
    setClearingQueue(true);
    setQueueMessage("");
    try {
      const result = await clearAdminJobQueue();
      setQueueMessage(result.message);
      setPage(1);
      await load();
    } catch (nextError) {
      setError((nextError as ApiError).message);
    } finally {
      setClearingQueue(false);
    }
  }

  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <Layout>
      <main className="content-page page-width admin-creations-page">
        <div className="page-heading admin-creations-heading">
          <span className="page-icon"><UsersRound /></span>
          <div><h1>{tr("全站创作管理", "All Creations")}</h1><p>{tr("查看每个用户创建的工作流任务、积分消费和最终视频。", "Review every user's workflow jobs, credit usage and delivered videos.")}</p></div>
          <button className="admin-clear-queue" type="button" disabled={summary.active <= 0 || clearingQueue} onClick={() => void clearQueue()}>
            {clearingQueue ? <LoaderCircle className="spin" /> : <Trash2 />}
            {clearingQueue ? tr("正在清空", "Clearing") : tr(`一键清空任务队列 (${summary.active})`, `Clear active queue (${summary.active})`)}
          </button>
        </div>

        <section className="admin-creation-summary">
          <article><UsersRound /><div><small>{tr("创作用户", "Creators")}</small><strong>{summary.users}</strong></div></article>
          <article><Video /><div><small>{tr("任务总数", "All jobs")}</small><strong>{summary.total}</strong></div></article>
          <article><Clock3 /><div><small>{tr("正在处理", "Active")}</small><strong>{summary.active}</strong></div></article>
          <article><CircleDollarSign /><div><small>{tr("成功任务积分", "Completed credits")}</small><strong>{summary.points}</strong></div></article>
        </section>

        <form className="admin-creation-toolbar" onSubmit={search}>
          <label className="search-box"><Search /><input value={queryInput} onChange={(event) => setQueryInput(event.target.value)} placeholder={tr("搜索账号、主题、任务 ID", "Search account, topic or job ID")} /></label>
          <select value={userId} onChange={(event) => { setUserId(event.target.value); setPage(1); }}>
            <option value="">{tr("全部用户", "All users")}</option>
            {users.map((item) => <option value={item.id} key={item.id}>{item.email || item.username}</option>)}
          </select>
          <select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}>
            {STATUS_OPTIONS.map(([value, zh, en]) => <option value={value} key={value}>{tr(zh, en)}</option>)}
          </select>
          <select value={workflowCode} onChange={(event) => { setWorkflowCode(event.target.value); setPage(1); }}>
            <option value="">{tr("全部工作流", "All workflows")}</option>
            {workflows.map((workflow) => <option value={workflow.code} key={`${workflow.category}-${workflow.code}`}>{workflow.code} · {workflow.name}</option>)}
            <option value="DRAFT_KEY_EXPORT">{tr("手工剪映导出", "Manual export")}</option>
          </select>
          <button type="submit"><Search />{tr("查询", "Search")}</button>
        </form>

        {queueMessage && <div className="notice success">{queueMessage}</div>}
        {error && <div className="notice error">{error}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" />{tr("正在加载全站创作记录", "Loading all creations")}</div> : jobs.length ? (
          <div className="admin-creation-list">
            {jobs.map((job) => (
              <article className="admin-creation-card" key={job.id}>
                <header>
                  <div className="admin-creation-user"><span>{(job.user.email || job.user.username || "?").slice(0, 1).toUpperCase()}</span><div><strong>{job.user.email || job.user.username}</strong><small>{job.user.username} · {job.user.id.slice(0, 8)}</small></div></div>
                  <span className={`record-status ${job.status}`}>{tr(...STATUS_TEXT[job.status])}</span>
                  <strong className="admin-creation-progress">{job.progress}%</strong>
                </header>
                <div className="admin-creation-body">
                  <div><h3>{job.display_title}</h3><p>{job.workflow_code} · {job.category} · {new Date(job.created_at * 1000).toLocaleString(locale)}</p></div>
                  <div className="admin-creation-facts"><span>{tr("积分", "Credits")} <strong>{job.price_points || 0}</strong></span><span>{tr("阶段", "Stage")} <strong>{job.stage}</strong></span><span>任务 <code>{job.id}</code></span></div>
                </div>
                <div className="record-progress"><i style={{ width: `${job.progress}%` }} /></div>
                {job.error && <div className="record-error">{job.error.message}</div>}
                {job.status === "failed" && <div className="record-error">{tr("失败阶段", "Failed stage")}: {job.failed_stage || job.stage}</div>}
                {job.status === "failed" && <div className="record-actions admin-creation-actions"><button type="button" disabled={retryingId === job.id} onClick={() => void retry(job)}>{retryingId === job.id ? <LoaderCircle className="spin" /> : <RefreshCw />}{retryingId === job.id ? tr("重新调用中", "Retrying") : tr("代用户重新调用（扣用户积分）", "Retry for user (charges user credits)")}</button></div>}
                {job.status === "succeeded" && job.results.length > 0 && <div className="record-actions admin-creation-actions">
                  {job.results.map((result, index) => <span className="record-result-actions" key={`${result.url}-${index}`}>
                    {result.type === "video" && <button type="button" onClick={() => setPreview(preview?.jobId === job.id && preview.url === (result.download_url || result.url) ? null : { jobId: job.id, url: result.download_url || result.url, poster: result.poster_url })}>{preview?.jobId === job.id && preview.url === (result.download_url || result.url) ? <X /> : <Play />}{preview?.jobId === job.id && preview.url === (result.download_url || result.url) ? tr("收起视频", "Close video") : result.download_url ? tr("播放高清原片", "Play original") : tr("播放视频", "Play video")}</button>}
                    <a href={result.download_url || result.url} target="_blank" rel="noreferrer" download={result.downloadable || undefined}><Download />{result.type === "video" && result.download_url ? tr("下载高清原片", "Download original") : `${tr("下载结果", "Download")} ${index + 1}`}</a>
                  </span>)}
                </div>}
                {preview?.jobId === job.id && <div className="record-video-preview"><video key={preview.url} src={preview.url} poster={preview.poster || undefined} controls autoPlay playsInline preload="metadata" /></div>}
              </article>
            ))}
          </div>
        ) : <div className="empty-state empty-stack"><FileText /><strong>{tr("没有符合条件的创作记录", "No matching creations")}</strong></div>}

        {total > pageSize && <nav className="pagination" aria-label={tr("全站创作记录分页", "All creations pagination")}>
          <button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft />{tr("上一页", "Previous")}</button>
          <span>{tr(`第 ${page} / ${pages} 页，共 ${total} 条`, `Page ${page} / ${pages} · ${total} total`)}</span>
          <button type="button" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>{tr("下一页", "Next")}<ChevronRight /></button>
        </nav>}
      </main>
    </Layout>
  );
}
