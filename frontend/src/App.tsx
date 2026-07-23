import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, BookOpen, Clock3, Download, Eye, FileText, Headphones, Heart, ImageIcon, LoaderCircle, LogOut, Mic2, Pause, Play, RotateCcw, Search, Sparkles, UploadCloud, Workflow as WorkflowIcon } from "lucide-react";
import { Link, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { approveRegistration, createJob, fetchCategories, fetchJob, fetchJobs, fetchMe, fetchRegistrationApplications, fetchSiteSummary, fetchVoices, fetchWorkflow, fetchWorkflows, generateSpeech, login, logout, register, rejectRegistration, retryJob, toggleFavorite as saveFavorite, uploadAsset } from "./api";
import type { AuthUser, InputField, Job, RegistrationApplication, SiteSummary, Voice, Workflow } from "./types";
import "./styles.css";

function formatMetric(value: number) {
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => { fetchMe().then((state) => setUser(state.user)).catch(() => setUser(null)); }, [location.pathname]);

  async function signOut() {
    await logout();
    setUser(null);
    navigate("/");
  }
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark"><Sparkles size={18} /></span>
          <span>AI 创作工坊</span>
        </Link>
        <nav className="topnav">
          <Link className={location.pathname === "/" ? "active" : ""} to="/">首页</Link>
          <Link className={location.pathname.startsWith("/workflows") ? "active" : ""} to="/workflows">工作流商店</Link>
          <Link className={location.pathname.startsWith("/voices") ? "active" : ""} to="/voices">配音广场</Link>
          <a href="https://www.coze.cn/user/4237988494589307?access_entrance=plugin_detail&sub_tab=plugins&tab=user_product" target="_blank" rel="noreferrer">扣子插件</a>
          <a href="https://ai.laobaiai.top/" target="_blank" rel="noreferrer">AI爆款创作平台</a>
        </nav>
        <div className="auth-nav">
          {user ? <>{user.role === "admin" && <Link to="/admin/registrations">注册审核</Link>}<Link to="/records">{user.email || user.username}</Link><button type="button" onClick={() => void signOut()}><LogOut size={14} />退出</button></> : <><Link to="/login">登录</Link><Link className="register-link" to="/register">申请注册</Link></>}
        </div>
      </header>
      {children}
    </div>
  );
}

function WorkflowCard({ workflow, favorite, onFavorite }: { workflow: Workflow; favorite: boolean; onFavorite: () => void }) {
  return (
    <article className="workflow-card">
      <Link className="card-media" to={`/workflows/${workflow.code}?category=${encodeURIComponent(workflow.category)}`}>
        {workflow.preview_url ? (
          workflow.preview_mime?.startsWith("video/") ? (
            <video src={workflow.preview_url} muted playsInline preload="metadata" />
          ) : (
            <img src={workflow.preview_url} alt={`${workflow.name}封面`} loading="lazy" />
          )
        ) : (
          <div className="media-fallback"><ImageIcon size={34} /><span>{workflow.code}</span></div>
        )}
        <span className="play-button"><Play size={17} fill="currentColor" /></span>
        {workflow.status === "coming_soon" && <span className="status-badge">即将上线</span>}
      </Link>
      <button
        type="button"
        className={`favorite-button ${favorite ? "selected" : ""}`}
        aria-label={favorite ? "取消收藏" : "收藏"}
        onClick={onFavorite}
      >
        <Heart size={19} fill={favorite ? "currentColor" : "none"} />
      </button>
      <div className="card-body">
        <Link className="card-title" to={`/workflows/${workflow.code}?category=${encodeURIComponent(workflow.category)}`}>
          <strong>{workflow.code}</strong> {workflow.name}
        </Link>
        <div className="tag-row">
          {workflow.tags.slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}
        </div>
        <div className="card-footer">
          <div className="metrics">
            <span><Eye size={14} />{formatMetric(workflow.stats.views)}</span>
            <span><Heart size={13} />{formatMetric(workflow.stats.favorites)}</span>
            <span><Download size={13} />{formatMetric(workflow.stats.downloads)}</span>
          </div>
          <Link to={`/workflows/${workflow.code}?category=${encodeURIComponent(workflow.category)}`}>点击查看</Link>
        </div>
      </div>
    </article>
  );
}

function CatalogPage() {
  const navigate = useNavigate();
  const [categories, setCategories] = useState<Array<{ name: string; count: number }>>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [category, setCategory] = useState("全部");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("newest");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [favorites, setFavorites] = useState<Set<string>>(new Set());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [visibleCount, setVisibleCount] = useState(24);
  const [catalogTotal, setCatalogTotal] = useState(0);

  useEffect(() => {
    fetchCategories().then(({ categories: result, total }) => {
      setCategories([{ name: "全部", count: total }, ...result]);
      setCatalogTotal(total);
    }).catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    fetchMe().then((state) => {
      setUser(state.user);
      setFavorites(new Set(state.workflow_favorites));
    }).catch(() => setUser(null));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      fetchWorkflows({ category, q: query, sort })
        .then(({ items }) => { setWorkflows(items); setError(""); })
        .catch((err: Error) => setError(err.message))
        .finally(() => setLoading(false));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [category, query, sort]);

  useEffect(() => setVisibleCount(24), [category, query, sort, favoritesOnly]);

  async function toggleFavorite(code: string) {
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/workflows")}`);
      return;
    }
    try {
      const result = await saveFavorite("workflow", code);
      setFavorites((current) => {
        const next = new Set(current);
        if (result.selected) next.add(code); else next.delete(code);
        return next;
      });
      setWorkflows((current) => current.map((workflow) => workflow.code === code
        ? { ...workflow, stats: { ...workflow.stats, favorites: result.favorites } }
        : workflow));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const filteredWorkflows = favoritesOnly
    ? workflows.filter((workflow) => favorites.has(workflow.code))
    : workflows;
  const visibleWorkflows = filteredWorkflows.slice(0, visibleCount);

  return (
    <Shell>
      <main className="catalog-page page-width">
        <section className="hero-copy">
          <span className="eyebrow">WORKFLOW MARKET</span>
          <h1>工作流商店</h1>
          <p>发现和使用高质量工作流</p>
        </section>

        <section className="toolbar-panel expanded-toolbar">
          <div className="category-tabs" role="tablist" aria-label="工作流分类">
            {categories.map((item) => (
              <button
                type="button"
                className={category === item.name ? "active" : ""}
                key={item.name}
                onClick={() => setCategory(item.name)}
              >
                {item.name}<em>{item.count}</em>
              </button>
            ))}
          </div>
          <div className="toolbar-actions">
            <label className="search-box">
              <Search size={17} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索工作流名称或编号" />
            </label>
          </div>
          <div className="catalog-filters">
            <button type="button" className={favoritesOnly ? "active" : ""} onClick={() => user ? setFavoritesOnly((value) => !value) : navigate(`/login?redirect=${encodeURIComponent("/workflows")}`)}>
              <Heart size={14} fill={favoritesOnly ? "currentColor" : "none"} />我的收藏
            </button>
            <span className="filter-divider" />
            {[
              ["newest", "最新发布"],
              ["favorites", "最多收藏"],
              ["downloads", "最多下载"],
              ["views", "最多浏览"],
              ["name", "名称排序"],
            ].map(([value, label]) => (
              <button type="button" className={sort === value ? "active" : ""} key={value} onClick={() => setSort(value)}>{label}</button>
            ))}
          </div>
        </section>

        <div className="catalog-summary">
          <span>共 {filteredWorkflows.length} 个工作流</span>
          {favoritesOnly && <small>只展示当前账号收藏</small>}
          {!query && category === "全部" && <small>目录总计 {catalogTotal} 个</small>}
        </div>

        {error && <div className="notice error">{error}</div>}
        {loading ? (
          <div className="loading-state"><LoaderCircle className="spin" /> 正在加载工作流</div>
        ) : visibleWorkflows.length ? (
          <>
          <section className="workflow-grid">
            {visibleWorkflows.map((workflow) => (
              <WorkflowCard
                key={`${workflow.category}-${workflow.code}`}
                workflow={workflow}
                favorite={favorites.has(workflow.code)}
                onFavorite={() => void toggleFavorite(workflow.code)}
              />
            ))}
          </section>
          {visibleCount < filteredWorkflows.length && (
            <button className="load-more" type="button" onClick={() => setVisibleCount((count) => count + 24)}>加载更多</button>
          )}
          </>
        ) : (
          <div className="empty-state">{favoritesOnly ? "暂无收藏的工作流" : "没有找到符合条件的工作流"}</div>
        )}
      </main>
    </Shell>
  );
}

type UploadedFile = { id: string; name: string; url: string };

function FieldControl({ field, value, onChange, onBusy }: {
  field: InputField;
  value: unknown;
  onChange: (value: unknown) => void;
  onBusy: (busy: boolean) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const files = (Array.isArray(value) ? value : value ? [value] : []) as UploadedFile[];
  const isAsset = ["image", "video", "audio", "file"].includes(field.type);

  async function handleFiles(selected: FileList | null) {
    if (!selected?.length) return;
    setUploading(true);
    onBusy(true);
    try {
      const limit = field.multiple ? field.max_files || selected.length : 1;
      const picked = Array.from(selected).slice(0, limit);
      const uploaded = await Promise.all(picked.map(async (file) => {
        const { asset } = await uploadAsset(file);
        return { id: asset.id, name: asset.name, url: asset.url };
      }));
      onChange(field.multiple ? uploaded : uploaded[0]);
    } finally {
      setUploading(false);
      onBusy(false);
    }
  }

  if (isAsset) {
    const accept = field.accept?.join(",") || (field.type === "file" ? ".docx,.txt" : `${field.type}/*`);
    return (
      <div className="asset-control">
        <label className="upload-drop">
          {uploading ? <LoaderCircle className="spin" /> : <UploadCloud />}
          <strong>{uploading ? "正在上传" : field.multiple ? "点击上传多份素材" : "点击上传素材"}</strong>
          <small>{field.multiple ? `最多 ${field.max_files || 9} 个文件` : accept}</small>
          <input type="file" accept={accept} multiple={field.multiple} onChange={(event) => void handleFiles(event.target.files)} />
        </label>
        {files.length > 0 && (
          <div className="uploaded-list">
            {files.map((file) => <span key={file.id}>{file.name}</span>)}
          </div>
        )}
      </div>
    );
  }

  if (field.type === "textarea") {
    return <textarea value={String(value ?? "")} placeholder={field.placeholder} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === "notice") {
    return <div className="field-notice">{String(value || field.default || "")}</div>;
  }
  if (field.type === "select") {
    return (
      <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
        {field.options?.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    );
  }
  return (
    <input
      type={field.type === "number" ? "number" : "text"}
      min={field.min}
      max={field.max}
      value={String(value ?? "")}
      placeholder={field.placeholder}
      onChange={(event) => onChange(field.type === "number" ? Number(event.target.value) : event.target.value)}
    />
  );
}

function JobProgress({ job, onRetry }: { job: Job; onRetry: () => void }) {
  const statusText: Record<Job["status"], string> = {
    queued: "等待执行", running: "正在生成", rendering: "正在渲染视频", succeeded: "生成完成", failed: "生成失败"
  };
  return (
    <section className="job-panel">
      <div className="job-heading">
        <div><span className={`status-dot ${job.status}`} />{statusText[job.status]}</div>
        <strong>{job.progress}%</strong>
      </div>
      <div className="progress-track"><i style={{ width: `${job.progress}%` }} /></div>
      <p>{job.stage}</p>
      {job.error && <div className="notice error">{job.error.message}</div>}
      {job.status === "failed" && <button className="secondary-button" type="button" onClick={onRetry}><RotateCcw size={15} />安全重试</button>}
    </section>
  );
}

function Results({ job }: { job: Job }) {
  if (job.status !== "succeeded") return null;
  return (
    <section className="result-panel">
      <div className="section-title"><span>生成结果</span><small>结果地址由后台统一托管</small></div>
      <div className={`result-grid ${job.results.length === 1 ? "single" : ""}`}>
        {job.results.map((result, index) => (
          <article className="result-item" key={`${result.url}-${index}`}>
            {result.type === "image" ? (
              <img src={result.url} alt={`生成结果 ${index + 1}`} />
            ) : result.type === "video" ? (
              <video src={result.url} poster={result.poster_url || undefined} controls playsInline />
            ) : (
              <div className="draft-result"><Sparkles /><strong>{result.format === "draft_key" ? "草稿 JSON 已生成" : "工作流 JSON 已生成"}</strong></div>
            )}
            <div className="result-actions">
              <span>结果 {index + 1}</span>
              <a href={result.url} target="_blank" rel="noreferrer">{result.format === "draft_key" ? "下载 draft_key JSON" : result.type === "draft" ? "下载工作流 JSON" : result.downloadable ? "查看 / 下载" : "打开结果"}</a>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function DetailPage() {
  const { code = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const category = searchParams.get("category") || "起号";
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [relatedWorkflows, setRelatedWorkflows] = useState<Workflow[]>([]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [assetBusy, setAssetBusy] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    fetchWorkflow(code, category)
      .then(({ workflow: result }) => {
        setWorkflow(result);
        setValues(Object.fromEntries(result.input_schema.map((field) => [field.name, field.default ?? ""])));
      })
      .catch((err: Error) => setError(err.message));
  }, [code, category]);

  useEffect(() => {
    fetchWorkflows({ category, q: "", sort: "newest" })
      .then(({ items }) => setRelatedWorkflows(items))
      .catch(() => setRelatedWorkflows([]));
  }, [category]);

  useEffect(() => {
    const savedJobId = localStorage.getItem(`workflow-job:${category}:${code.toUpperCase()}`);
    if (!savedJobId) return;
    fetchJob(savedJobId)
      .then(({ job: restored }) => setJob(restored))
      .catch(() => localStorage.removeItem(`workflow-job:${category}:${code.toUpperCase()}`));
  }, [code, category]);

  useEffect(() => {
    if (job) localStorage.setItem(`workflow-job:${category}:${code.toUpperCase()}`, job.id);
  }, [job?.id, code, category]);

  useEffect(() => {
    if (!job || ["succeeded", "failed"].includes(job.status)) return;
    pollRef.current = window.setInterval(() => {
      fetchJob(job.id).then(({ job: next }) => setJob(next)).catch((err: Error) => setError(err.message));
    }, 2000);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [job?.id, job?.status]);

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
    if (!workflow || workflow.status !== "online") return;
    setBusy(true);
    setError("");
    try {
      const response = await createJob(workflow.code, workflow.category, providerInputs);
      setJob(response.job);
    } catch (err) {
      const message = (err as Error).message;
      if (message === "请先登录") {
        navigate(`/login?redirect=${encodeURIComponent(`/workflows/${workflow.code}?category=${category}`)}`);
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!job) return;
    setBusy(true);
    try {
      const response = await retryJob(job.id);
      setJob(response.job);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!workflow) {
    return <Shell><main className="page-width"><div className="loading-state">{error || "正在加载工作流…"}</div></main></Shell>;
  }

  return (
    <Shell>
      <main className="detail-page page-width">
        <button type="button" className="back-button" onClick={() => navigate(-1)}><ArrowLeft size={17} />返回工作流广场</button>
        {relatedWorkflows.length > 1 && (
          <nav className="workflow-switcher" aria-label="切换同类工作流">
            <span>同类工作流</span>
            <div>
              {relatedWorkflows.map((item) => (
                <Link
                  className={item.code === workflow.code ? "active" : ""}
                  key={item.code}
                  to={`/workflows/${item.code}?category=${encodeURIComponent(category)}`}
                >
                  {item.code} {item.name}
                </Link>
              ))}
            </div>
          </nav>
        )}
        <section className="detail-hero">
          <div className="detail-preview">
            {workflow.preview_url ? (
              workflow.preview_mime?.startsWith("video/")
                ? <video src={workflow.preview_url} controls playsInline />
                : <img src={workflow.preview_url} alt={workflow.name} />
            ) : <div className="media-fallback"><ImageIcon size={48} /><span>{workflow.code}</span></div>}
          </div>
          <div className="detail-copy">
            <div className="detail-kicker"><span>{workflow.category}</span><span>{workflow.generation_mode === "workflow_template" ? "视频工作流" : workflow.generation_mode === "draft" ? "剪映原生视频" : workflow.output_type === "video" ? "视频生成" : "图片生成"}</span></div>
            <h1>{workflow.code} · {workflow.name}</h1>
            <p>{workflow.description}</p>
            <div className="detail-tags">{workflow.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            <div className="detail-metrics">
              <span><Eye size={16} /> {workflow.stats.views} 次查看</span>
              <span><Heart size={15} /> {workflow.stats.favorites} 人收藏</span>
              <span><Download size={15} /> {workflow.stats.downloads} 次使用</span>
            </div>
            {workflow.code.startsWith("OWN") ? (
              <div className="owned-workflow-badge"><Sparkles size={16} />本站自有工作流，可直接在下方生成</div>
            ) : (
              <a
                className="download-access-button"
                href={`/api/v1/workflows/${encodeURIComponent(workflow.code)}/download/json?category=${encodeURIComponent(category)}`}
                download
              >
                <Download size={17} />直接下载工作流 JSON
              </a>
            )}
          </div>
        </section>

        <div className="detail-layout">
          <section className="generator-panel">
            <div className="section-title">
              <span>{workflow.generation_mode === "workflow_template" ? "第一阶段：生成工作流" : "一键生成视频"}</span>
              <small>{workflow.generation_mode === "workflow_template" ? "输入主题，生成可导入扣子的 JSON" : workflow.generation_mode === "draft" ? "后台自动生成草稿并通过 Windows 剪映原生导出" : "第三方密钥已由后台配置，无需填写"}</small>
            </div>
            <form onSubmit={(event) => void submit(event)}>
              {workflow.input_schema.map((field) => (
                <label className="form-field" key={field.name}>
                  <span>{field.label}{field.required && <em>*</em>}</span>
                  <FieldControl
                    field={field}
                    value={values[field.name]}
                    onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
                    onBusy={setAssetBusy}
                  />
                </label>
              ))}
              {workflow.status !== "online" && (
                <div className="notice">输入项已经按工作流整理完成；后台发布并配置工作流 ID 后即可生成。</div>
              )}
              {error && <div className="notice error">{error}</div>}
              <button className="primary-button" disabled={busy || assetBusy || workflow.status !== "online"} type="submit">
                {busy ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />}
                {busy ? "正在生成" : workflow.status === "online" ? workflow.generation_mode === "workflow_template" ? "生成视频工作流" : "立即生成视频" : "后台接入中"}
              </button>
            </form>
          </section>
          <aside className="execution-column">
            <div className="execution-placeholder">
              <strong>执行过程</strong>
              <p>{workflow.generation_mode === "workflow_template" ? "当前先生成扣子工作流 JSON；你导入测试并发布后，后台再切换为自动调用和视频渲染。" : workflow.generation_mode === "draft" ? "提交后由后台运行扣子，渲染机自动生成剪映草稿并原生导出 MP4；浏览器无需安装桥接器。" : "提交后可在这里查看排队、生成、渲染和完成状态。刷新页面不会泄露任何后台密钥。"}</p>
            </div>
            {job && <JobProgress job={job} onRetry={() => void retry()} />}
          </aside>
        </div>
        {job && <Results job={job} />}
      </main>
    </Shell>
  );
}

function HomePage() {
  const [summary, setSummary] = useState<SiteSummary | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchSiteSummary().then(setSummary).catch((err: Error) => setError(err.message));
  }, []);

  return (
    <Shell>
      <main className="home-page page-width">
        <section className="home-hero">
          <span className="eyebrow">AI CREATION PLATFORM</span>
          <h1>一站式 AI 创作服务平台</h1>
          <p>工作流商店、配音广场和视频生成工具集中在同一个后台，用户只需要填写创作内容。</p>
          <div className="home-actions"><Link className="primary-link" to="/workflows">探索工作流</Link><Link to="/voices">进入配音广场</Link></div>
        </section>
        {summary && (
          <section className="live-stat-grid" aria-label="平台实时数据">
            <div><strong>{summary.catalog.workflows}</strong><span>真实工作流</span></div>
            <div><strong>{summary.catalog.categories}</strong><span>内容分类</span></div>
            <div><strong>{summary.jobs.total}</strong><span>生成任务</span></div>
            <div><strong>{summary.activity.downloads}</strong><span>实际下载</span></div>
          </section>
        )}
        {error && <div className="notice error">首页数据加载失败：{error}</div>}
        <section className="feature-section">
          <div className="section-heading"><span>核心功能</span><h2>探索我们的 AI 服务生态</h2></div>
          <div className="feature-grid">
            <Link to="/workflows"><WorkflowIcon /><h3>工作流商店</h3><p>智能工作流模板，按起号、电商、养生、减肥和财经快速生成。</p><span>立即查看 →</span></Link>
            <Link to="/voices"><Mic2 /><h3>配音广场</h3><p>{summary?.voice_service.message || "读取服务器当前可用的真实音色与配音服务。"}</p><span>{summary?.voice_service.available ? `${summary.catalog.voices} 个音色可用 →` : "查看服务状态 →"}</span></Link>
            <a href="https://www.coze.cn/user/4237988494589307?access_entrance=plugin_detail&sub_tab=plugins&tab=user_product" target="_blank" rel="noreferrer"><Sparkles /><h3>扣子插件</h3><p>扩展工作流所需的图片、音频、草稿和内容处理能力。</p><span>打开插件页 →</span></a>
          </div>
        </section>
      </main>
    </Shell>
  );
}

function VoicesPage() {
  const navigate = useNavigate();
  const [voices, setVoices] = useState<Voice[]>([]);
  const [query, setQuery] = useState("");
  const [gender, setGender] = useState("all");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [favorites, setFavorites] = useState<Set<string>>(new Set());
  const [user, setUser] = useState<AuthUser | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [playingId, setPlayingId] = useState("");
  const [text, setText] = useState("");
  const [speed, setSpeed] = useState(1);
  const [generating, setGenerating] = useState(false);
  const [audio, setAudio] = useState<{ url: string; duration: number; message: string } | null>(null);
  const [error, setError] = useState("");
  const [voiceService, setVoiceService] = useState<{ available: boolean; provider: string; message: string }>({ available: false, provider: "", message: "正在读取配音服务" });
  const auditionAudio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    Promise.all([fetchVoices(), fetchMe()]).then(([catalog, auth]) => {
      setVoices(catalog.voices);
      setSelectedId(catalog.voices[0]?.id || "");
      setVoiceService({ available: catalog.available, provider: catalog.provider, message: catalog.message });
      setUser(auth.user);
      setFavorites(new Set(auth.voice_favorites));
    }).catch((err: Error) => setError(err.message));
    return () => { auditionAudio.current?.pause(); };
  }, []);

  const filteredVoices = voices.filter((voice) => {
    const matchesQuery = !query || `${voice.name} ${voice.description} ${voice.id}`.toLowerCase().includes(query.toLowerCase());
    const matchesGender = gender === "all" || voice.gender === gender;
    return matchesQuery && matchesGender && (!favoritesOnly || favorites.has(voice.id));
  });
  const selectedVoice = voices.find((voice) => voice.id === selectedId);

  async function audition(voice: Voice) {
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/voices")}`);
      return;
    }
    if (playingId === voice.id) {
      auditionAudio.current?.pause();
      setPlayingId("");
      return;
    }
    auditionAudio.current?.pause();
    setPlayingId(voice.id);
    setError("");
    try {
      const result = await generateSpeech(`你好，我是${voice.name}。这是一段真实音色试听。`, voice.id, speed);
      setAudio(result.audio);
      const player = new Audio(result.audio.url);
      auditionAudio.current = player;
      player.onended = () => setPlayingId("");
      player.onerror = () => setPlayingId("");
      await player.play();
    } catch (err) {
      setPlayingId("");
      setError((err as Error).message);
    }
  }
  async function toggleVoiceFavorite(voiceId: string) {
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/voices")}`);
      return;
    }
    try {
      const result = await saveFavorite("voice", voiceId);
      setFavorites((current) => {
        const next = new Set(current);
        if (result.selected) next.add(voiceId); else next.delete(voiceId);
        return next;
      });
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function submitSpeech(event: FormEvent) {
    event.preventDefault();
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/voices")}`);
      return;
    }
    if (!selectedVoice || !text.trim()) {
      setError("请选择音色并输入配音文案");
      return;
    }
    setGenerating(true);
    setError("");
    try {
      const result = await generateSpeech(text, selectedVoice.id, speed);
      setAudio(result.audio);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <Shell>
      <main className="voices-page page-width">
        <section className="page-heading voice-heading"><span className="page-icon"><Headphones /></span><div><h1>配音广场</h1><p>搜索音色、在线试听并生成可下载配音。</p></div></section>
        <div className={`service-status ${voiceService.available ? "ready" : "unavailable"}`}>
          <strong>{voiceService.available ? "真实配音服务可用" : "配音服务当前不可用"}</strong>
          <span>{voiceService.message}</span>
        </div>
        <section className="voice-toolbar">
          <label className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称或ID..." /></label>
          <div className="voice-filter-row">
            {[['all','不限'],['female','女声'],['male','男声'],['boy','男童'],['girl','女童'],['neutral','中性']].map(([value,label]) => <button className={gender === value ? "active" : ""} key={value} type="button" onClick={() => setGender(value)}>{label}</button>)}
            <button className={favoritesOnly ? "active" : ""} type="button" onClick={() => user ? setFavoritesOnly((value) => !value) : navigate(`/login?redirect=${encodeURIComponent("/voices")}`)}><Heart size={13} />我的收藏</button>
          </div>
        </section>
        <div className="voice-layout">
          <section>
            <div className="catalog-summary">共 {filteredVoices.length} 个音色</div>
            <div className="voice-grid">
              {filteredVoices.map((voice) => (
                <article className={`voice-card ${selectedId === voice.id ? "selected" : ""}`} key={voice.id} onClick={() => setSelectedId(voice.id)}>
                  <div className="voice-avatar"><Mic2 /></div>
                  <div className="voice-info"><h3>{voice.name}</h3><p>{voice.description}</p><span>{voice.gender_label} · {voice.language} · {voice.model}</span></div>
                  <div className="voice-card-actions">
                    <button type="button" aria-label="试听" onClick={(event) => { event.stopPropagation(); void audition(voice); }}>{playingId === voice.id ? <Pause /> : <Play />}</button>
                    <button className={favorites.has(voice.id) ? "selected" : ""} type="button" aria-label="收藏" onClick={(event) => { event.stopPropagation(); void toggleVoiceFavorite(voice.id); }}><Heart fill={favorites.has(voice.id) ? "currentColor" : "none"} /></button>
                  </div>
                </article>
              ))}
            </div>
            {!filteredVoices.length && <div className="empty-state">{favoritesOnly ? "暂无收藏的音色" : voiceService.message}</div>}
          </section>
          <aside className="tts-panel">
            <div className="section-title"><span>制作配音</span><small>当前使用 {selectedVoice?.name || "未选择"}</small></div>
            <form onSubmit={(event) => void submitSpeech(event)}>
              <label><span>配音文案</span><textarea maxLength={5000} value={text} onChange={(event) => setText(event.target.value)} placeholder="请输入需要配音的文案..." /><small>{text.length} / 5000 字</small></label>
              <label><span>当前语速：{speed.toFixed(1)}x</span><input type="range" min="0.5" max="2" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} /></label>
              {error && <div className="notice error">{error}</div>}
              <button className="primary-button" disabled={generating || !voiceService.available || !selectedVoice} type="submit">{generating ? <LoaderCircle className="spin" /> : <Mic2 />}{generating ? "生成中..." : "生成配音"}</button>
            </form>
            {audio && <div className="audio-result"><strong>真实配音已生成</strong><audio src={audio.url} controls /><a href={audio.url} download>下载配音</a><small>时长约 {audio.duration.toFixed(1)} 秒</small></div>}
          </aside>
        </div>
      </main>
    </Shell>
  );
}

function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const isRegister = mode === "register";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      if (isRegister) {
        const result = await register(email);
        setSuccess(result.message);
        setEmail("");
        return;
      }
      await login(email, password);
      const redirect = searchParams.get("redirect");
      navigate(redirect?.startsWith("/") && !redirect.startsWith("//") ? redirect : "/workflows");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell>
      <main className="auth-page page-width">
        <section className="auth-card">
          <span className="brand-mark"><Sparkles /></span>
          <h1>{isRegister ? "申请注册" : "欢迎回来"}</h1>
          <p>{isRegister ? "提交邮箱后等待管理员审核，通过后登录密码会发送到邮箱" : "使用审核通过邮件中的邮箱和密码登录"}</p>
          <form onSubmit={(event) => void submit(event)}>
            <label><span>{isRegister ? "申请邮箱" : "邮箱 / 用户名"}</span><input autoComplete="username" type={isRegister ? "email" : "text"} value={email} onChange={(event) => setEmail(event.target.value)} placeholder={isRegister ? "name@example.com" : "请输入邮箱或旧用户名"} required />{isRegister && <small>管理员审核通过后，系统会把登录密码发到此邮箱</small>}</label>
            {!isRegister && <label><span>登录密码</span><input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="请输入邮件中的登录密码" required /></label>}
            {error && <div className="notice error">{error}</div>}
            {success && <div className="notice success">{success}</div>}
            <button className="primary-button" disabled={busy || Boolean(success)} type="submit">{busy && <LoaderCircle className="spin" />}{busy ? isRegister ? "提交中..." : "登录中..." : isRegister ? "提交注册申请" : "登录"}</button>
          </form>
          <div className="auth-switch">{isRegister ? <>已经收到通过邮件？<Link to="/login">立即登录</Link></> : <>还没有账户？<Link to="/register">申请注册</Link></>}</div>
        </section>
      </main>
    </Shell>
  );
}

const JOB_STATUS_TEXT: Record<Job["status"], string> = {
  queued: "等待执行",
  running: "正在生成",
  rendering: "正在渲染",
  succeeded: "生成完成",
  failed: "生成失败",
};

function RegistrationAdminPage() {
  const navigate = useNavigate();
  const [applications, setApplications] = useState<RegistrationApplication[]>([]);
  const [status, setStatus] = useState("pending");
  const [emailService, setEmailService] = useState<{ configured: boolean; sender?: string | null; message: string }>({ configured: false, message: "正在检查邮件服务" });
  const [busyId, setBusyId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadApplications(selectedStatus = status) {
    setLoading(true);
    setError("");
    try {
      const auth = await fetchMe();
      if (!auth.user) {
        navigate(`/login?redirect=${encodeURIComponent("/admin/registrations")}`);
        return;
      }
      if (auth.user.role !== "admin") {
        setError("当前账号不是管理员，不能查看注册申请");
        return;
      }
      const result = await fetchRegistrationApplications(selectedStatus);
      setApplications(result.items);
      setEmailService(result.email_service);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadApplications(status); }, [status]);

  async function review(applicationId: string, action: "approve" | "reject") {
    setBusyId(applicationId);
    setError("");
    setMessage("");
    try {
      const result = action === "approve"
        ? await approveRegistration(applicationId)
        : await rejectRegistration(applicationId);
      setMessage(result.message);
      await loadApplications(status);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <Shell>
      <main className="content-page page-width admin-registration-page">
        <div className="page-heading">
          <span className="page-icon"><FileText /></span>
          <div><h1>注册申请审核</h1><p>通过后系统生成登录密码，并真实发送到申请邮箱。</p></div>
        </div>
        <div className={`service-status ${emailService.configured ? "ready" : "unavailable"}`}>
          <strong>{emailService.configured ? "审批邮件可发送" : "审批邮件未配置"}</strong>
          <span>{emailService.message}{emailService.sender ? ` · 发件人 ${emailService.sender}` : ""}</span>
        </div>
        <div className="admin-filter-row">
          {[["pending", "待审核"], ["approved", "已通过"], ["rejected", "已拒绝"], ["all", "全部"]].map(([value, label]) => (
            <button type="button" className={status === value ? "active" : ""} key={value} onClick={() => setStatus(value)}>{label}</button>
          ))}
        </div>
        {error && <div className="notice error">{error}</div>}
        {message && <div className="notice success">{message}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" /> 正在加载注册申请</div> : applications.length ? (
          <div className="application-list">
            {applications.map((application) => (
              <article className="application-card" key={application.id}>
                <div><strong>{application.email}</strong><p>申请时间：{new Date(application.created_at * 1000).toLocaleString("zh-CN")}</p>{application.delivery_error && <small>上次发信失败：{application.delivery_error}</small>}</div>
                <span className={`application-status ${application.status}`}>{({ pending: "待审核", delivering: "发信中", approved: "已通过", rejected: "已拒绝" } as const)[application.status]}</span>
                {application.status === "pending" && <div className="application-actions"><button type="button" disabled={!emailService.configured || busyId === application.id} onClick={() => void review(application.id, "approve")}>通过并发密码</button><button className="danger" type="button" disabled={busyId === application.id} onClick={() => void review(application.id, "reject")}>拒绝</button></div>}
              </article>
            ))}
          </div>
        ) : <div className="empty-state">当前没有该状态的注册申请</div>}
      </main>
    </Shell>
  );
}

function RecordsPage() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = () => {
      fetchJobs()
        .then(({ items }) => {
          if (!active) return;
          setJobs(items);
          setError("");
          if (items.some((job) => !["succeeded", "failed"].includes(job.status))) {
            timer = window.setTimeout(load, 2000);
          }
        })
        .catch((err: Error) => {
          if (!active) return;
          if (err.message === "请先登录") navigate(`/login?redirect=${encodeURIComponent("/records")}`);
          else setError(err.message);
        })
        .finally(() => active && setLoading(false));
    };
    load();
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, []);

  return (
    <Shell>
      <main className="content-page page-width">
        <div className="page-heading">
          <span className="page-icon"><Clock3 /></span>
          <div><h1>创作记录</h1><p>查看任务进度、恢复生成现场和打开最终结果。</p></div>
        </div>
        {error && <div className="notice error">{error}</div>}
        {loading ? <div className="loading-state"><LoaderCircle className="spin" /> 正在加载创作记录</div> : jobs.length ? (
          <div className="record-list">
            {jobs.map((job) => (
              <article className="record-card" key={job.id}>
                <div className="record-main">
                  <span className={`record-status ${job.status}`}>{JOB_STATUS_TEXT[job.status]}</span>
                  <div>
                    <h3>{job.workflow_code} · {job.category}</h3>
                    <p>{new Date(job.created_at * 1000).toLocaleString("zh-CN")} · {job.stage}</p>
                  </div>
                </div>
                <div className="record-progress"><i style={{ width: `${job.progress}%` }} /></div>
                <div className="record-actions">
                  <span>{job.progress}%</span>
                  {job.results.map((result, index) => <a key={`${result.url}-${index}`} href={result.url} target="_blank" rel="noreferrer">结果 {index + 1}</a>)}
                  <Link to={`/workflows/${job.workflow_code}?category=${encodeURIComponent(job.category)}`}>打开工作流</Link>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty-state empty-stack"><FileText /><strong>还没有创作记录</strong><Link to="/workflows">选择一个工作流开始生成</Link></div>
        )}
      </main>
    </Shell>
  );
}

function HelpPage() {
  return (
    <Shell>
      <main className="content-page page-width help-page">
        <div className="page-heading">
          <span className="page-icon"><BookOpen /></span>
          <div><h1>使用帮助</h1><p>从选择工作流到拿到视频，整个过程都在当前网站完成。</p></div>
        </div>
        <section className="help-steps">
          <article><em>01</em><h3>选择工作流</h3><p>按起号、电商、养生、减肥或财经分类筛选，也可以直接搜索编号和名称。</p></article>
          <article><em>02</em><h3>填写内容与素材</h3><p>用户只填写主题、文案和上传文件；扣子、米核等后台参数不会展示。</p></article>
          <article><em>03</em><h3>等待生成与渲染</h3><p>任务会依次经过排队、生成和视频渲染，离开详情页后仍可从创作记录恢复。</p></article>
          <article><em>04</em><h3>预览和下载结果</h3><p>图片直接显示，视频直接播放；成功结果可在页面打开或下载。</p></article>
        </section>
        <section className="faq-panel">
          <h2>常见问题</h2>
          <details open><summary>为什么按钮显示“后台接入中”？</summary><p>页面输入结构已经完成，但对应扣子工作流 ID 或视频渲染服务还没有配置，配置后会自动开放生成。</p></details>
          <details><summary>刷新页面会丢失任务吗？</summary><p>不会。详情页会恢复最近一次任务，全部历史任务也会保存在“创作记录”中。</p></details>
          <details><summary>支持哪些素材？</summary><p>支持常见图片、视频和音频格式；小说推文工作流额外支持 DOCX 和 TXT 文档。</p></details>
          <details><summary>用户能看到第三方密钥吗？</summary><p>不能。第三方 Token、工作流 ID 和渲染密钥只在 FastAPI 后台读取。</p></details>
        </section>
      </main>
    </Shell>
  );
}

function NotFound() {
  return <Shell><main className="page-width"><div className="empty-state"><h2>页面不存在</h2><Link to="/workflows">返回工作流商店</Link></div></main></Shell>;
}

export default function App() {
  return (
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/workflows" element={<CatalogPage />} />
        <Route path="/workflows/:code" element={<DetailPage />} />
        <Route path="/voices" element={<VoicesPage />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/admin/registrations" element={<RegistrationAdminPage />} />
        <Route path="/records" element={<RecordsPage />} />
        <Route path="/help" element={<HelpPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
