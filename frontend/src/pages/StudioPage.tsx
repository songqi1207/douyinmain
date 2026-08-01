import {
  BookOpen,
  Check,
  Cigarette,
  Laptop,
  LockKeyhole,
  Play,
  Settings,
  ShieldCheck,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  ApiError,
  createJob,
  fetchDraftKeyRenderStatus,
  fetchJob,
  fetchJobs,
  fetchSiteSummary,
  fetchWorkflows,
  retryJob,
} from "../api";
import { useAuth } from "../auth";
import { JobProgress, Results } from "../components/JobViews";
import { Layout } from "../components/Layout";
import { WorkflowInputSettingsDialog } from "../components/WorkflowInputSettingsDialog";
import { useJobPolling } from "../hooks";
import type { Job, RenderStatus, SiteSummary, Workflow } from "../types";

const WORKFLOW_CHOICES = [
  {
    code: "OWN01",
    label: "书单视频",
    short: "书单",
    description: "把一本书的气质变成完整荐书短片",
    placeholder: "输入书名，也可写成：书名｜作者",
    example: "克林索尔的最后夏天｜黑塞",
    icon: BookOpen,
  },
  {
    code: "OWN02",
    label: "香烟故事",
    short: "香烟",
    description: "围绕一款香烟生成克制的情感独白",
    placeholder: "输入香烟名称",
    example: "中华",
    icon: Cigarette,
  },
  {
    code: "OWN03",
    label: "神话人物",
    short: "神话",
    description: "生成有画面感的中国神话人物解说",
    placeholder: "输入神名或神话主题",
    example: "哪吒",
    icon: Sparkles,
  },
] as const;

const EMPTY_RENDER_STATUS: RenderStatus = {
  configured: false,
  device_online: false,
  central_configured: false,
  devices: [],
  message: "正在检查剪映设备",
};

export function StudioPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedCode = (searchParams.get("workflow") || "OWN01").toUpperCase();
  const initialCode = WORKFLOW_CHOICES.some((item) => item.code === requestedCode)
    ? requestedCode as (typeof WORKFLOW_CHOICES)[number]["code"]
    : "OWN01";
  const [selectedCode, setSelectedCode] = useState(initialCode);
  const [theme, setTheme] = useState("");
  const [workflows, setWorkflows] = useState<Record<string, Workflow>>({});
  const [renderStatus, setRenderStatus] = useState<RenderStatus>(EMPTY_RENDER_STATUS);
  const [summary, setSummary] = useState<SiteSummary | null>(null);
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);
  const [initialJob, setInitialJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState("");
  const [configMessage, setConfigMessage] = useState("");
  const [configuringWorkflowCode, setConfiguringWorkflowCode] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const { job, setJob } = useJobPolling(initialJob, setError);

  const selected = WORKFLOW_CHOICES.find((item) => item.code === selectedCode)!;
  const workflow = workflows[selectedCode];
  const published = workflow?.status === "online" && workflow.output_type === "draft";
  const renderReady = renderStatus.configured;
  const ready = Boolean(user && !user.must_change_password && published && renderReady);
  const visibleRecentJobs = useMemo(() => recentJobs.map((item) => (
    item.id === job?.id ? job : item
  )), [recentJobs, job]);

  useEffect(() => {
    Promise.all([
      fetchWorkflows({ category: "自有工作流", q: "", sort: "newest" }),
      fetchDraftKeyRenderStatus(),
      fetchSiteSummary(),
    ]).then(([workflowResult, statusResult, summaryResult]) => {
      setWorkflows(Object.fromEntries(workflowResult.items.map((item) => [item.code, item])));
      setRenderStatus(statusResult);
      setSummary(summaryResult);
    }).catch((nextError: Error) => setError(nextError.message));
  }, []);

  useEffect(() => {
    if (!user) {
      setRecentJobs([]);
      return;
    }
    fetchJobs({ pageSize: 4 })
      .then((result) => setRecentJobs(result.items))
      .catch(() => setRecentJobs([]));
  }, [user?.id, job?.status]);

  useEffect(() => {
    const key = `studio-job:${selectedCode}`;
    const saved = localStorage.getItem(key);
    if (!saved || !user) {
      setInitialJob(null);
      setJob(null);
      return;
    }
    fetchJob(saved)
      .then(({ job: restored }) => {
        setInitialJob(restored);
        setJob(restored);
      })
      .catch(() => localStorage.removeItem(key));
  }, [selectedCode, user?.id]);

  useEffect(() => {
    if (job) localStorage.setItem(`studio-job:${job.workflow_code}`, job.id);
  }, [job?.id]);

  useEffect(() => {
    if (job?.status === "succeeded" && job.results.length > 0) {
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [job?.id, job?.status, job?.results.length]);

  const readiness = useMemo(() => [
    {
      label: "账号",
      ready: Boolean(user && !user.must_change_password),
      detail: authLoading ? "检查中" : !user ? "登录后开始" : user.must_change_password ? "请先修改密码" : "已登录",
      icon: user?.must_change_password ? LockKeyhole : ShieldCheck,
      action: !user ? "/login?redirect=/" : user.must_change_password ? "/account/security" : "",
    },
    {
      label: "工作流",
      ready: Boolean(published),
      detail: !workflow ? "检查中" : published ? "已发布" : "后台尚未发布",
      icon: WandSparkles,
      action: "",
    },
    {
      label: "剪映设备",
      ready: renderReady,
      detail: renderReady
        ? renderStatus.device_online ? "本机助手在线" : "云端渲染可用"
        : "需要完成一次配对",
      icon: Laptop,
      action: renderReady ? "" : "/devices",
    },
  ], [user, authLoading, published, workflow, renderReady, renderStatus.device_online]);

  function chooseWorkflow(code: (typeof WORKFLOW_CHOICES)[number]["code"]) {
    setSelectedCode(code);
    setTheme("");
    setError("");
    setConfigMessage("");
    setSearchParams({ workflow: code });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!theme.trim()) {
      setError("请先输入主题内容");
      return;
    }
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent(`/?workflow=${selectedCode}`)}`);
      return;
    }
    if (user.must_change_password) {
      navigate("/account/security");
      return;
    }
    if (!published) {
      setError("该工作流后台尚未发布完成");
      return;
    }
    if (!renderReady) {
      navigate("/devices");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await createJob(selectedCode, "自有工作流", { theme: theme.trim() });
      setInitialJob(response.job);
      setJob(response.job);
      localStorage.setItem(`studio-job:${selectedCode}`, response.job.id);
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "login_required") navigate(`/login?redirect=${encodeURIComponent("/")}`);
      else if (apiError.code === "password_change_required") navigate("/account/security");
      else if (apiError.code === "render_device_required") navigate("/devices");
      else setError(apiError.message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!job) return;
    setRetrying(true);
    setError("");
    try {
      const response = await retryJob(job.id);
      setInitialJob(response.job);
      setJob(response.job);
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "render_device_required") navigate("/devices");
      else setError(apiError.message);
    } finally {
      setRetrying(false);
    }
  }

  function resetCreation() {
    setTheme("");
    setInitialJob(null);
    setJob(null);
    setError("");
    localStorage.removeItem(`studio-job:${selectedCode}`);
  }

  return (
    <Layout>
      <main className="studio-page page-width">
        <section className="studio-hero">
          <div className="studio-hero-copy">
            <span className="eyebrow">ONE IDEA. ONE VIDEO.</span>
            <h1>输入一个主题，<em>直接生成视频</em></h1>
            <p>文案、配音、画面、剪映草稿和 MP4 导出都由后台自动完成。你只需要决定今天想讲什么。</p>
            <div className="hero-proof">
              <span><Check />密钥只在服务器</span>
              <span><Check />进度自动保存</span>
              <span><Check />剪映原生导出</span>
            </div>
          </div>
          <div className="studio-orbit" aria-hidden="true">
            <div className="orbit-core"><Play fill="currentColor" /></div>
            <span className="orbit-label one">主题</span>
            <span className="orbit-label two">草稿</span>
            <span className="orbit-label three">视频</span>
          </div>
        </section>

        <section className="creation-workspace" aria-labelledby="creation-title">
          <div className="workspace-heading">
            <div><span>创作工作台</span><h2 id="creation-title">今天想做哪类视频？</h2></div>
            <small>只需要 1 个输入项</small>
          </div>
          <div className="workflow-choice-grid" role="tablist" aria-label="视频类型">
            {WORKFLOW_CHOICES.map((choice) => {
              const Icon = choice.icon;
              return (
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedCode === choice.code}
                  className={selectedCode === choice.code ? "active" : ""}
                  key={choice.code}
                  onClick={() => chooseWorkflow(choice.code)}
                >
                  <span className="choice-icon"><Icon /></span>
                  <span><strong>{choice.label}</strong><small>{choice.description}</small></span>
                  <i>{selectedCode === choice.code && <Check />}</i>
                </button>
              );
            })}
          </div>

          <div className="workspace-grid">
            <form className="studio-form" onSubmit={(event) => void submit(event)}>
              <div className="studio-form-label">
                <span>主题内容</span>
                <div>
                  <small>示例：{selected.example}</small>
                  {user?.role === "admin" && (
                    <button
                      type="button"
                      className="studio-input-config"
                      onClick={() => setConfiguringWorkflowCode(selectedCode)}
                      aria-label={`配置${selected.label}输入参数`}
                      title={`配置${selected.label}输入参数`}
                    >
                      <Settings />
                    </button>
                  )}
                </div>
              </div>
              <textarea
                autoFocus
                maxLength={120}
                value={theme}
                onChange={(event) => setTheme(event.target.value)}
                placeholder={selected.placeholder}
              />
              <div className="input-meta"><span>{theme.length} / 120</span><span>按你的主题自动生成完整脚本与画面</span></div>
              <div className="readiness-grid">
                {readiness.map(({ label, ready: itemReady, detail, icon: Icon, action }) => {
                  const content = (
                    <>
                      <span className={itemReady ? "ready" : ""}>{itemReady ? <Check /> : <Icon />}</span>
                      <div><strong>{label}</strong><small>{detail}</small></div>
                    </>
                  );
                  return action
                    ? <Link key={label} to={action} className="readiness-item actionable">{content}</Link>
                    : <div key={label} className="readiness-item">{content}</div>;
                })}
              </div>
              {error && <div className="notice error" role="alert">{error}</div>}
              {configMessage && <div className="notice success"><Check />{configMessage}</div>}
              <button className="studio-submit" disabled={busy || !theme.trim()} type="submit">
                {busy ? <span className="spin-ring" /> : <Sparkles />}
                {busy ? "正在创建任务" : !user ? "登录后开始创作" : !ready ? "完成准备后生成" : "一键生成视频"}
              </button>
              <p className="privacy-note"><ShieldCheck />不会向浏览器发送生成服务或渲染密钥</p>
            </form>

            <aside className="workspace-status">
              {job ? (
                <>
                  <div className="current-job-title">
                    <span>{selected.short}视频</span>
                    <strong>{job.display_title || theme}</strong>
                  </div>
                  <JobProgress job={job} onRetry={() => void retry()} retrying={retrying} />
                  <div ref={resultRef}>
                    <Results job={job} compact />
                  </div>
                  {job.status === "succeeded" && (
                    <button className="secondary-button create-again" type="button" onClick={resetCreation}>
                      <Sparkles size={15} />再创作一个
                    </button>
                  )}
                </>
              ) : (
                <div className="workspace-empty">
                  <span><WandSparkles /></span>
                  <strong>等待你的主题</strong>
                  <p>提交后，这里会实时显示生成、草稿和剪映导出进度。</p>
                  <ol>
                    <li><i>1</i>生成内容与配音</li>
                    <li><i>2</i>创建画面和剪映草稿</li>
                    <li><i>3</i>导出并返回 MP4</li>
                  </ol>
                </div>
              )}
            </aside>
          </div>
        </section>

        {configuringWorkflowCode && (
          <WorkflowInputSettingsDialog
            workflowCode={configuringWorkflowCode}
            workflowLabel={WORKFLOW_CHOICES.find((item) => item.code === configuringWorkflowCode)?.label || configuringWorkflowCode}
            onClose={() => setConfiguringWorkflowCode(null)}
            onSaved={() => {
              const label = WORKFLOW_CHOICES.find((item) => item.code === configuringWorkflowCode)?.label || configuringWorkflowCode;
              setConfigMessage(`${label}输入参数已保存并立即生效`);
              setConfiguringWorkflowCode(null);
            }}
          />
        )}

        <section className="studio-lower-grid">
          <div className="recent-work-card">
            <div className="section-title"><span>最近创作</span><Link to="/records">查看全部</Link></div>
            {user ? visibleRecentJobs.length ? (
              <div className="mini-job-list">
                {visibleRecentJobs.map((item) => (
                  <Link to="/records" key={item.id}>
                    <span className={`mini-status ${item.status}`} />
                    <div><strong>{item.display_title}</strong><small>{item.category} · {new Date(item.created_at * 1000).toLocaleDateString("zh-CN")}</small></div>
                    <em>{item.progress}%</em>
                  </Link>
                ))}
              </div>
            ) : <div className="small-empty">你的第一个作品会出现在这里</div>
            : <div className="small-empty"><Link to="/login?redirect=/">登录后查看创作记录</Link></div>}
          </div>
          <div className="platform-status-card">
            <div className="section-title"><span>平台能力</span><small>实时状态</small></div>
            <div className="platform-metrics">
              <div><strong>{summary?.catalog.online_workflows ?? "—"}</strong><span>在线工作流</span></div>
              <div><strong>{summary?.jobs.succeeded ?? "—"}</strong><span>完成任务</span></div>
              <div><strong>{summary?.catalog.voices ?? "—"}</strong><span>真实音色</span></div>
            </div>
            <Link className="status-link" to="/workflows">探索更多工作流 <span>→</span></Link>
          </div>
        </section>
      </main>
    </Layout>
  );
}
