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
import { usePreferences } from "../preferences";
import type { Job, RenderStatus, SiteSummary, Workflow } from "../types";

const WORKFLOW_CHOICES = [
  {
    code: "OWN01",
    label: "书单视频",
    labelEn: "Book Video",
    short: "书单",
    shortEn: "Book",
    description: "把一本书的气质变成完整荐书短片",
    descriptionEn: "Turn the character of a book into a complete short video",
    placeholder: "输入书名，也可写成：书名｜作者",
    placeholderEn: "Enter a title, or use: Book | Author",
    example: "克林索尔的最后夏天｜黑塞",
    exampleEn: "The Old Man and the Sea | Hemingway",
    icon: BookOpen,
  },
  {
    code: "OWN02",
    label: "香烟故事",
    labelEn: "Cigarette Story",
    short: "香烟",
    shortEn: "Story",
    description: "围绕一款香烟生成克制的情感独白",
    descriptionEn: "Create a restrained emotional monologue around a cigarette",
    placeholder: "输入香烟名称",
    placeholderEn: "Enter a cigarette name",
    example: "中华",
    exampleEn: "Marlboro",
    icon: Cigarette,
  },
  {
    code: "OWN03",
    label: "神话人物",
    labelEn: "Mythology",
    short: "神话",
    shortEn: "Myth",
    description: "生成有画面感的中国神话人物解说",
    descriptionEn: "Create a cinematic narration about a Chinese mythological figure",
    placeholder: "输入神名或神话主题",
    placeholderEn: "Enter a deity or mythology topic",
    example: "哪吒",
    exampleEn: "Nezha",
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
  const { language, tr, locale } = usePreferences();
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
      label: tr("账号", "Account"),
      ready: Boolean(user && !user.must_change_password),
      detail: authLoading ? tr("检查中", "Checking") : !user ? tr("登录后开始", "Sign in to start") : user.must_change_password ? tr("请先修改密码", "Change password first") : tr("已登录", "Signed in"),
      icon: user?.must_change_password ? LockKeyhole : ShieldCheck,
      action: !user ? "/login?redirect=/" : user.must_change_password ? "/account/security" : "",
    },
    {
      label: tr("工作流", "Workflow"),
      ready: Boolean(published),
      detail: !workflow ? tr("检查中", "Checking") : published ? tr("已发布", "Published") : tr("后台尚未发布", "Not published"),
      icon: WandSparkles,
      action: "",
    },
    {
      label: tr("剪映设备", "Render device"),
      ready: renderReady,
      detail: renderReady
        ? renderStatus.device_online ? tr("本机助手在线", "Local assistant online") : tr("云端渲染可用", "Cloud rendering ready")
        : tr("需要完成一次配对", "Pair a device first"),
      icon: Laptop,
      action: renderReady ? "" : "/devices",
    },
  ], [user, authLoading, published, workflow, renderReady, renderStatus.device_online, language]);

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
      setError(tr("请先输入主题内容", "Enter a topic first"));
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
      setError(tr("该工作流后台尚未发布完成", "This workflow has not been published yet"));
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
            <span className="eyebrow">VIDEOLAB / CREATE</span>
            <h1>{tr("把想法交给流程，", "Give the idea to the workflow,")}<em>{tr("把时间留给创作", "keep your time for creativity")}</em></h1>
            <p>{tr("一个主题就够了。文案、声音、画面、剪映草稿和成片导出在同一条创作链路里自动完成。", "One topic is enough. Script, voice, visuals, editing draft and final export all happen in one creative flow.")}</p>
            <div className="hero-proof">
              <span><Check />{tr("过程可见", "Visible progress")}</span>
              <span><Check />{tr("离开页面也会继续", "Keeps running in the background")}</span>
              <span><Check />{tr("完成后自动通知", "Completion notifications")}</span>
            </div>
          </div>
          <div className="studio-orbit">
            <div className="flow-card-heading"><span>{tr("本次创作链路", "CREATION FLOW")}</span><em>{renderReady ? "READY" : "CHECKING"}</em></div>
            <ol className="flow-steps">
              <li><i>01</i><div><strong>{tr("一句主题", "One topic")}</strong><small>{tr("告诉系统你今天想讲什么", "Tell us what you want to say")}</small></div></li>
              <li><i>02</i><div><strong>{tr("自动编排", "Auto production")}</strong><small>{tr("内容、配音与画面同步生成", "Script, voice and visuals generated together")}</small></div></li>
              <li><i>03</i><div><strong>{tr("交付成片", "Final delivery")}</strong><small>{tr("剪映原生导出并回传网页", "Native export returned to the web")}</small></div></li>
            </ol>
            <div className="flow-card-footer"><span><Play fill="currentColor" />{renderReady ? tr("创作通道已就绪", "Creation channel ready") : tr("等待创作通道", "Waiting for channel")}</span><strong>{workflow?.pricing?.price_points ?? 0} P</strong></div>
          </div>
        </section>

        <section className="creation-workspace" aria-labelledby="creation-title">
          <div className="workspace-heading">
            <div><span>NEW CREATION</span><h2 id="creation-title">{tr("选择一个创作入口", "Choose a creation type")}</h2></div>
            <small>{tr("一个主题，完整交付", "One topic, complete delivery")}</small>
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
                  <span><strong>{language === "en" ? choice.labelEn : choice.label}</strong><small>{language === "en" ? choice.descriptionEn : choice.description}</small></span>
                  <i>{selectedCode === choice.code && <Check />}</i>
                </button>
              );
            })}
          </div>

          <div className="workspace-grid">
            <form className="studio-form" onSubmit={(event) => void submit(event)}>
              <div className="studio-form-label">
                <span>{tr("主题内容", "Topic")}</span>
                <div>
                  <small>{tr("示例", "Example")}: {language === "en" ? selected.exampleEn : selected.example}</small>
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
                placeholder={language === "en" ? selected.placeholderEn : selected.placeholder}
              />
              <div className="input-meta"><span>{theme.length} / 120</span><span>{tr("按你的主题自动生成完整脚本与画面", "Generate the complete script and visuals from your topic")}</span></div>
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
                {busy ? tr("正在创建任务", "Creating task") : !user ? tr("登录后开始创作", "Sign in to create") : !ready ? tr("完成准备后生成", "Complete setup to generate") : tr(`一键生成视频 · ${workflow?.pricing?.price_points ?? 0} 积分`, `Generate video · ${workflow?.pricing?.price_points ?? 0} credits`)}
              </button>
              <p className="privacy-note"><ShieldCheck />{tr("不会向浏览器发送生成服务或渲染密钥", "Generation and rendering keys never reach your browser")}</p>
            </form>

            <aside className="workspace-status">
              {job ? (
                <>
                  <div className="current-job-title">
                    <span>{language === "en" ? selected.shortEn : selected.short}{tr("视频", " video")}</span>
                    <strong>{job.display_title || theme}</strong>
                  </div>
                  <JobProgress job={job} onRetry={() => void retry()} retrying={retrying} />
                  <div ref={resultRef}>
                    <Results job={job} compact />
                  </div>
                  {job.status === "succeeded" && (
                    <button className="secondary-button create-again" type="button" onClick={resetCreation}>
                      <Sparkles size={15} />{tr("再创作一个", "Create another")}
                    </button>
                  )}
                </>
              ) : (
                <div className="workspace-empty">
                  <span><WandSparkles /></span>
                  <strong>{tr("等待你的主题", "Waiting for your topic")}</strong>
                  <p>{tr("提交后，这里会实时显示生成、草稿和剪映导出进度。", "After submission, generation, draft and export progress will appear here.")}</p>
                  <ol>
                    <li><i>1</i>{tr("生成内容与配音", "Generate script and voice")}</li>
                    <li><i>2</i>{tr("创建画面和剪映草稿", "Create visuals and draft")}</li>
                    <li><i>3</i>{tr("导出并返回 MP4", "Export and return MP4")}</li>
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
            <div className="section-title"><span>{tr("最近创作", "Recent creations")}</span><Link to="/records">{tr("查看全部", "View all")}</Link></div>
            {user ? visibleRecentJobs.length ? (
              <div className="mini-job-list">
                {visibleRecentJobs.map((item) => (
                  <Link to="/records" key={item.id}>
                    <span className={`mini-status ${item.status}`} />
                    <div><strong>{item.display_title}</strong><small>{item.category} · {new Date(item.created_at * 1000).toLocaleDateString(locale)}</small></div>
                    <em>{item.progress}%</em>
                  </Link>
                ))}
              </div>
            ) : <div className="small-empty">{tr("你的第一个作品会出现在这里", "Your first creation will appear here")}</div>
            : <div className="small-empty"><Link to="/login?redirect=/">{tr("登录后查看创作记录", "Sign in to view creations")}</Link></div>}
          </div>
          <div className="platform-status-card">
            <div className="section-title"><span>{tr("平台能力", "Platform capacity")}</span><small>{tr("实时状态", "Live status")}</small></div>
            <div className="platform-metrics">
              <div><strong>{summary?.catalog.online_workflows ?? "—"}</strong><span>{tr("在线工作流", "Workflows")}</span></div>
              <div><strong>{summary?.jobs.succeeded ?? "—"}</strong><span>{tr("完成任务", "Completed")}</span></div>
              <div><strong>{summary?.catalog.voices ?? "—"}</strong><span>{tr("真实音色", "Voices")}</span></div>
            </div>
            <Link className="status-link" to="/workflows">{tr("探索更多工作流", "Explore workflows")} <span>→</span></Link>
          </div>
        </section>
      </main>
    </Layout>
  );
}
