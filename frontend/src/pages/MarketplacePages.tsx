import {
  ArrowLeft,
  ArrowRight,
  Download,
  Eye,
  Heart,
  ImageIcon,
  LoaderCircle,
  Play,
  Search,
  Sparkles,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import {
  ApiError,
  createJob,
  fetchCategories,
  fetchJobs,
  fetchWorkflow,
  fetchWorkflows,
  retryJob,
  toggleFavorite,
} from "../api";
import { useAuth } from "../auth";
import { FieldControl, type UploadedFile } from "../components/FieldControl";
import { JobProgress, Results } from "../components/JobViews";
import { Layout } from "../components/Layout";
import { useJobPolling } from "../hooks";
import { usePreferences } from "../preferences";
import type { Job, Workflow } from "../types";

function formatMetric(value: number) {
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function WorkflowCard({
  workflow,
  favorite,
  onFavorite,
}: {
  workflow: Workflow;
  favorite: boolean;
  onFavorite: () => void;
}) {
  const { tr } = usePreferences();
  const detailUrl = `/workflows/${workflow.code}?category=${encodeURIComponent(workflow.category)}`;
  return (
    <article className="workflow-card">
      <Link className="card-media" to={detailUrl}>
        {workflow.preview_url ? (
          workflow.preview_mime?.startsWith("video/")
            ? <video src={workflow.preview_url} muted playsInline preload="metadata" />
            : <img src={workflow.preview_url} alt={`${workflow.name}封面`} loading="lazy" />
        ) : <div className="media-fallback"><ImageIcon /><span>{workflow.code}</span></div>}
        <span className="play-button"><Play fill="currentColor" /></span>
        {workflow.status === "coming_soon" && <span className="status-badge">{tr("即将上线", "Coming soon")}</span>}
      </Link>
      <button className={`favorite-button ${favorite ? "selected" : ""}`} type="button" aria-label={favorite ? tr("取消收藏", "Remove favorite") : tr("收藏", "Favorite")} onClick={onFavorite}>
        <Heart fill={favorite ? "currentColor" : "none"} />
      </button>
      <div className="card-body">
        <Link className="card-title" to={detailUrl}><strong>{workflow.code}</strong> {workflow.name}</Link>
        <div className="tag-row">{workflow.tags.slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}</div>
        <div className="card-footer">
          <div className="metrics">
            <span><Eye />{formatMetric(workflow.stats.views)}</span>
            <span><Heart />{formatMetric(workflow.stats.favorites)}</span>
            <span><Download />{formatMetric(workflow.stats.downloads)}</span>
          </div>
          <Link to={detailUrl}>{tr("查看详情", "View details")}</Link>
        </div>
      </div>
    </article>
  );
}

export function CatalogPage() {
  const { user, workflow_favorites } = useAuth();
  const { tr, locale } = usePreferences();
  const navigate = useNavigate();
  const [categories, setCategories] = useState<Array<{ name: string; count: number }>>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [category, setCategory] = useState("全部");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("newest");
  const [favorites, setFavorites] = useState(new Set<string>());
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [videoJobs, setVideoJobs] = useState<Job[]>([]);
  const [videosLoading, setVideosLoading] = useState(false);

  useEffect(() => setFavorites(new Set(workflow_favorites)), [workflow_favorites.join("|")]);

  useEffect(() => {
    fetchCategories()
      .then(({ categories: items, total }) => setCategories([{ name: "全部", count: total }, ...items]))
      .catch((nextError: Error) => setError(nextError.message));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      fetchWorkflows({ category, q: query, sort })
        .then(({ items }) => { setWorkflows(items); setError(""); })
        .catch((nextError: Error) => setError(nextError.message))
        .finally(() => setLoading(false));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [category, query, sort]);

  useEffect(() => {
    let cancelled = false;
    if (!user) {
      setVideoJobs([]);
      setVideosLoading(false);
      return () => { cancelled = true; };
    }
    setVideosLoading(true);
    fetchJobs({ page: 1, pageSize: 12, status: "succeeded" })
      .then(({ items }) => {
        if (!cancelled) setVideoJobs(items.filter((job) => job.results.some((result) => result.type === "video")).slice(0, 4));
      })
      .catch(() => {
        if (!cancelled) setVideoJobs([]);
      })
      .finally(() => {
        if (!cancelled) setVideosLoading(false);
      });
    return () => { cancelled = true; };
  }, [user?.id]);

  async function save(code: string) {
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/workflows")}`);
      return;
    }
    try {
      const result = await toggleFavorite("workflow", code);
      setFavorites((current) => {
        const next = new Set(current);
        if (result.selected) next.add(code); else next.delete(code);
        return next;
      });
      setWorkflows((current) => current.map((item) => item.code === code
        ? { ...item, stats: { ...item.stats, favorites: result.favorites } }
        : item));
    } catch (nextError) {
      setError((nextError as Error).message);
    }
  }

  const visible = favoritesOnly ? workflows.filter((item) => favorites.has(item.code)) : workflows;
  return (
    <Layout>
      <main className="catalog-page page-width">
        <section className="hero-copy"><span className="eyebrow">WORKFLOW LIBRARY</span><h1>{tr("工作流库", "Workflow Library")}</h1><p>{tr("探索更多创作能力，或下载成熟工作流供自己使用。", "Explore proven creative workflows and find the right starting point for your content.")}</p></section>
        {user && (
          <section className="catalog-user-videos" aria-labelledby="catalog-user-videos-title">
            <div className="catalog-video-heading">
              <div>
                <span className="eyebrow">MY CREATIONS</span>
                <h2 id="catalog-user-videos-title">{tr("我做的视频", "My videos")}</h2>
                <p>{tr("最新生成的成片会自动出现在这里。", "Your latest finished videos appear here automatically.")}</p>
              </div>
              <Link to="/records">{tr("查看全部作品", "View all creations")}<ArrowRight /></Link>
            </div>
            {videosLoading ? (
              <div className="catalog-video-state"><LoaderCircle className="spin" />{tr("正在加载成片", "Loading your videos")}</div>
            ) : videoJobs.length ? (
              <div className="catalog-video-grid">
                {videoJobs.map((job) => {
                  const result = job.results.find((item) => item.type === "video")!;
                  return (
                    <article className="catalog-video-card" key={job.id}>
                      <div className="catalog-video-media">
                        <video src={result.url} poster={result.poster_url || undefined} controls playsInline preload="none" />
                      </div>
                      <div className="catalog-video-body">
                        <div>
                          <strong>{job.display_title}</strong>
                          <span>{job.workflow_code} · {new Date(job.created_at * 1000).toLocaleDateString(locale)}</span>
                        </div>
                        <a href={result.download_url || result.url} target="_blank" rel="noreferrer" download={result.downloadable || undefined} aria-label={tr(`下载 ${job.display_title}`, `Download ${job.display_title}`)}><Download /></a>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="catalog-video-empty">
                <Play />
                <div><strong>{tr("还没有完成的视频", "No finished videos yet")}</strong><span>{tr("完成第一次生成后，成片会显示在这里。", "Your first completed video will show up here.")}</span></div>
                <Link to="/business">{tr("去创作", "Create video")}</Link>
              </div>
            )}
          </section>
        )}
        <section className="toolbar-panel expanded-toolbar">
          <div className="category-tabs" role="tablist" aria-label={tr("工作流分类", "Workflow categories")}>
            {categories.map((item) => <button type="button" className={category === item.name ? "active" : ""} key={item.name} onClick={() => setCategory(item.name)}>{item.name}<em>{item.count}</em></button>)}
          </div>
          <div className="toolbar-actions"><label className="search-box"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("搜索名称、编号或标签", "Search name, code or tag")} /></label></div>
          <div className="catalog-filters">
            <button type="button" className={favoritesOnly ? "active" : ""} onClick={() => user ? setFavoritesOnly((value) => !value) : navigate(`/login?redirect=${encodeURIComponent("/workflows")}`)}><Heart fill={favoritesOnly ? "currentColor" : "none"} />{tr("我的收藏", "Favorites")}</button>
            {[["newest", tr("最新", "Newest")], ["favorites", tr("收藏最多", "Most saved")], ["downloads", tr("使用最多", "Most used")], ["views", tr("浏览最多", "Most viewed")], ["name", tr("按名称", "Name")]].map(([value, label]) => <button type="button" className={sort === value ? "active" : ""} key={value} onClick={() => setSort(value)}>{label}</button>)}
          </div>
        </section>
        <div className="catalog-summary">{tr(`共 ${visible.length} 个工作流`, `${visible.length} workflows`)}</div>
        {error && <div className="notice error">{error}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" />{tr("正在加载工作流", "Loading workflows")}</div> : visible.length ? (
          <section className="workflow-grid">
            {visible.map((workflow) => <WorkflowCard key={`${workflow.category}-${workflow.code}`} workflow={workflow} favorite={favorites.has(workflow.code)} onFavorite={() => void save(workflow.code)} />)}
          </section>
        ) : <div className="empty-state">{tr("没有找到符合条件的工作流", "No matching workflows found")}</div>}
      </main>
    </Layout>
  );
}

export function DetailPage() {
  const { tr } = usePreferences();
  const { code = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const category = searchParams.get("category") || "起号";
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [initialJob, setInitialJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [assetBusy, setAssetBusy] = useState(false);
  const [error, setError] = useState("");
  const { job, setJob } = useJobPolling(initialJob, setError);

  useEffect(() => {
    fetchWorkflow(code, category)
      .then(({ workflow: result }) => {
        setWorkflow(result);
        setValues(Object.fromEntries(result.input_schema.map((field) => [field.name, field.default ?? ""])));
      })
      .catch((nextError: Error) => setError(nextError.message));
  }, [code, category]);

  const providerInputs = useMemo(() => {
    const result: Record<string, unknown> = {};
    Object.entries(values).forEach(([name, value]) => {
      if (Array.isArray(value)) result[name] = value.map((item: UploadedFile) => item.id);
      else if (value && typeof value === "object" && "id" in value) result[name] = (value as UploadedFile).id;
      else result[name] = value;
    });
    return result;
  }, [values]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!workflow) return;
    setBusy(true);
    setError("");
    try {
      const response = await createJob(workflow.code, workflow.category, providerInputs);
      setInitialJob(response.job);
      setJob(response.job);
    } catch (nextError) {
      const apiError = nextError as ApiError;
      if (apiError.code === "login_required") navigate(`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`);
      else if (apiError.code === "password_change_required") navigate("/account/security");
      else if (apiError.code === "render_device_required") navigate("/devices");
      else setError(apiError.message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!job) return;
    setBusy(true);
    try {
      const response = await retryJob(job.id);
      setInitialJob(response.job);
      setJob(response.job);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!workflow) return <Layout><main className="page-width"><div className="loading-state">{error || "正在加载工作流"}</div></main></Layout>;
  const owned = workflow.code.startsWith("OWN");
  return (
    <Layout>
      <main className="detail-page page-width">
        <button type="button" className="back-button" onClick={() => navigate(-1)}><ArrowLeft />{tr("返回工作流", "Back to workflows")}</button>
        <section className="detail-hero">
          <div className="detail-preview">
            {workflow.preview_url ? workflow.preview_mime?.startsWith("video/")
              ? <video src={workflow.preview_url} controls playsInline />
              : <img src={workflow.preview_url} alt={workflow.name} />
              : <div className="media-fallback"><ImageIcon /><span>{workflow.code}</span></div>}
          </div>
          <div className="detail-copy">
            <div className="detail-kicker"><span>{workflow.category}</span><span>{workflow.output_type === "video" || workflow.generation_mode === "draft" ? tr("视频生成", "Video generation") : tr("创作工作流", "Creative workflow")}</span></div>
            <h1>{workflow.name}</h1>
            <p>{workflow.description}</p>
            <div className="detail-tags">{workflow.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            <div className="detail-metrics"><span><Eye />{tr(`${workflow.stats.views} 次查看`, `${workflow.stats.views} views`)}</span><span><Heart />{tr(`${workflow.stats.favorites} 人收藏`, `${workflow.stats.favorites} saves`)}</span><span><Download />{tr(`${workflow.stats.downloads} 次使用`, `${workflow.stats.downloads} uses`)}</span></div>
            {owned ? <Link className="download-access-button" to={`/?workflow=${workflow.code}`}><Sparkles />{tr("到一键工作台创作", "Create in Studio")}</Link>
              : <a className="download-access-button" href={`/api/v1/workflows/${encodeURIComponent(workflow.code)}/download/json?category=${encodeURIComponent(category)}`} download><Download />{tr("下载工作流 JSON", "Download workflow JSON")}</a>}
          </div>
        </section>
        {!owned && (
          <div className="detail-layout">
            <section className="generator-panel">
              <div className="section-title"><span>{tr("在线运行", "Run online")}</span><small>{tr("第三方密钥由服务器安全注入", "Provider keys are securely injected by the server")}</small></div>
              <form onSubmit={(event) => void submit(event)}>
                {workflow.input_schema.map((field) => (
                  <label className="form-field" key={field.name}>
                    <span>{field.label}{field.required && <em>*</em>}</span>
                    <FieldControl field={field} value={values[field.name]} onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))} onBusy={setAssetBusy} />
                  </label>
                ))}
                {error && <div className="notice error">{error}</div>}
                <button className="primary-button" disabled={busy || assetBusy || workflow.status !== "online"} type="submit">{busy ? <LoaderCircle className="spin" /> : <Sparkles />}{busy ? tr("正在创建任务", "Creating task") : workflow.status === "online" ? tr(`开始生成 · ${workflow.pricing?.price_points ?? 0} 积分`, `Generate · ${workflow.pricing?.price_points ?? 0} credits`) : tr("后台接入中", "Connecting")}</button>
              </form>
            </section>
            <aside className="execution-column">{job ? <JobProgress job={job} onRetry={() => void retry()} retrying={busy} /> : <div className="execution-placeholder"><strong>{tr("执行过程", "Execution")}</strong><p>{tr("任务提交后，这里会显示生成和渲染状态。", "Generation and rendering status will appear here after submission.")}</p></div>}</aside>
          </div>
        )}
        {job && <Results job={job} />}
      </main>
    </Layout>
  );
}
