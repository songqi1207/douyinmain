import {
  ArrowLeft,
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
        {workflow.status === "coming_soon" && <span className="status-badge">即将上线</span>}
      </Link>
      <button className={`favorite-button ${favorite ? "selected" : ""}`} type="button" aria-label={favorite ? "取消收藏" : "收藏"} onClick={onFavorite}>
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
          <Link to={detailUrl}>查看详情</Link>
        </div>
      </div>
    </article>
  );
}

export function CatalogPage() {
  const { user, workflow_favorites } = useAuth();
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
        <section className="hero-copy"><span className="eyebrow">WORKFLOW LIBRARY</span><h1>工作流商店</h1><p>探索更多创作能力，或把成熟工作流下载到自己的扣子空间。</p></section>
        <section className="toolbar-panel expanded-toolbar">
          <div className="category-tabs" role="tablist" aria-label="工作流分类">
            {categories.map((item) => <button type="button" className={category === item.name ? "active" : ""} key={item.name} onClick={() => setCategory(item.name)}>{item.name}<em>{item.count}</em></button>)}
          </div>
          <div className="toolbar-actions"><label className="search-box"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、编号或标签" /></label></div>
          <div className="catalog-filters">
            <button type="button" className={favoritesOnly ? "active" : ""} onClick={() => user ? setFavoritesOnly((value) => !value) : navigate(`/login?redirect=${encodeURIComponent("/workflows")}`)}><Heart fill={favoritesOnly ? "currentColor" : "none"} />我的收藏</button>
            {[["newest", "最新"], ["favorites", "收藏最多"], ["downloads", "使用最多"], ["views", "浏览最多"], ["name", "按名称"]].map(([value, label]) => <button type="button" className={sort === value ? "active" : ""} key={value} onClick={() => setSort(value)}>{label}</button>)}
          </div>
        </section>
        <div className="catalog-summary">共 {visible.length} 个工作流</div>
        {error && <div className="notice error">{error}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" />正在加载工作流</div> : visible.length ? (
          <section className="workflow-grid">
            {visible.map((workflow) => <WorkflowCard key={`${workflow.category}-${workflow.code}`} workflow={workflow} favorite={favorites.has(workflow.code)} onFavorite={() => void save(workflow.code)} />)}
          </section>
        ) : <div className="empty-state">没有找到符合条件的工作流</div>}
      </main>
    </Layout>
  );
}

export function DetailPage() {
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
        <button type="button" className="back-button" onClick={() => navigate(-1)}><ArrowLeft />返回工作流</button>
        <section className="detail-hero">
          <div className="detail-preview">
            {workflow.preview_url ? workflow.preview_mime?.startsWith("video/")
              ? <video src={workflow.preview_url} controls playsInline />
              : <img src={workflow.preview_url} alt={workflow.name} />
              : <div className="media-fallback"><ImageIcon /><span>{workflow.code}</span></div>}
          </div>
          <div className="detail-copy">
            <div className="detail-kicker"><span>{workflow.category}</span><span>{workflow.output_type === "video" || workflow.generation_mode === "draft" ? "视频生成" : "创作工作流"}</span></div>
            <h1>{workflow.name}</h1>
            <p>{workflow.description}</p>
            <div className="detail-tags">{workflow.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            <div className="detail-metrics"><span><Eye />{workflow.stats.views} 次查看</span><span><Heart />{workflow.stats.favorites} 人收藏</span><span><Download />{workflow.stats.downloads} 次使用</span></div>
            {owned ? <Link className="download-access-button" to={`/?workflow=${workflow.code}`}><Sparkles />到一键工作台创作</Link>
              : <a className="download-access-button" href={`/api/v1/workflows/${encodeURIComponent(workflow.code)}/download/json?category=${encodeURIComponent(category)}`} download><Download />下载工作流 JSON</a>}
          </div>
        </section>
        {!owned && (
          <div className="detail-layout">
            <section className="generator-panel">
              <div className="section-title"><span>在线运行</span><small>第三方密钥由服务器安全注入</small></div>
              <form onSubmit={(event) => void submit(event)}>
                {workflow.input_schema.map((field) => (
                  <label className="form-field" key={field.name}>
                    <span>{field.label}{field.required && <em>*</em>}</span>
                    <FieldControl field={field} value={values[field.name]} onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))} onBusy={setAssetBusy} />
                  </label>
                ))}
                {error && <div className="notice error">{error}</div>}
                <button className="primary-button" disabled={busy || assetBusy || workflow.status !== "online"} type="submit">{busy ? <LoaderCircle className="spin" /> : <Sparkles />}{busy ? "正在创建任务" : workflow.status === "online" ? "开始生成" : "后台接入中"}</button>
              </form>
            </section>
            <aside className="execution-column">{job ? <JobProgress job={job} onRetry={() => void retry()} retrying={busy} /> : <div className="execution-placeholder"><strong>执行过程</strong><p>任务提交后，这里会显示生成和渲染状态。</p></div>}</aside>
          </div>
        )}
        {job && <Results job={job} />}
      </main>
    </Layout>
  );
}
