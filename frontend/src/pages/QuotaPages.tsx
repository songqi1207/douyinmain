import { Cloud, Coins, HardDrive, History, LoaderCircle, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { adjustAdminUserQuota, fetchAccountQuota, fetchAdminUserQuotas } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { QuotaLedgerEntry, UserQuota } from "../types";

function formatBytes(value: number) {
  if (value < 0) return "不限";
  if (value < 1024 * 1024) return `${Math.max(0, value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const LEDGER_LABELS: Record<QuotaLedgerEntry["event_type"], string> = {
  reserve: "创建任务，冻结额度",
  consume: "生成成功，确认消费",
  refund: "任务失败，自动退回",
  adjust: "管理员调整额度",
};

export function AccountUsagePage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [quota, setQuota] = useState<UserQuota | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/account/usage")}`);
      return;
    }
    fetchAccountQuota()
      .then(({ quota: result }) => { setQuota(result); setError(""); })
      .catch((nextError) => setError((nextError as Error).message))
      .finally(() => setLoading(false));
  }, [authLoading, user?.id]);

  const storagePercent = quota?.unlimited
    ? 0
    : Math.min(100, Math.round((quota?.storage_used_bytes || 0) / Math.max(1, quota?.storage_limit_bytes || 1) * 100));

  return (
    <Layout>
      <main className="content-page page-width usage-page">
        <div className="page-heading"><span className="page-icon"><Cloud /></span><div><h1>额度与云存储</h1><p>查看视频生成次数、云端空间和每一笔额度变化。</p></div></div>
        {error && <div className="notice error">{error}</div>}
        {loading || !quota ? <div className="loading-state"><LoaderCircle className="spin" />正在读取额度</div> : (
          <>
            <section className="quota-overview-grid">
              <article><span><Coins /></span><div><small>可用生成额度</small><strong>{quota.unlimited ? "不限" : `${quota.generation_balance} 次`}</strong><p>{quota.generation_reserved ? `${quota.generation_reserved} 次正在任务中` : "当前没有冻结额度"}</p></div></article>
              <article><span><HardDrive /></span><div><small>视频云存储</small><strong>{formatBytes(quota.storage_used_bytes)} / {formatBytes(quota.storage_limit_bytes)}</strong><p>{quota.unlimited ? "管理员账号不限制空间" : `剩余 ${formatBytes(quota.storage_available_bytes)}`}</p></div></article>
              <article className={quota.can_generate ? "ready" : "blocked"}><span><ShieldCheck /></span><div><small>创作状态</small><strong>{quota.can_generate ? "可以生成视频" : "额度或存储不足"}</strong><p>{quota.can_generate ? "每次成功生成消费 1 次" : "请删除旧视频或联系管理员扩容"}</p></div></article>
            </section>
            {!quota.unlimited && <div className="storage-meter"><div><span>云存储使用率</span><strong>{storagePercent}%</strong></div><progress max="100" value={storagePercent} /></div>}
            <section className="quota-rules-card">
              <h2>消费规则</h2>
              <ol><li>创建任务时先冻结 1 次生成额度。</li><li>视频成功后正式消费；任务失败自动退回。</li><li>网页预览版和高清下载版都计入实际云存储。</li><li>删除创作记录中的云端视频后立即释放空间。</li></ol>
            </section>
            <section className="quota-ledger-card">
              <div className="section-title"><span>额度明细</span><History /></div>
              {quota.ledger?.length ? quota.ledger.map((entry) => (
                <article key={entry.id}><div><strong>{LEDGER_LABELS[entry.event_type]}</strong><small>{entry.detail || "额度变动"} · {new Date(entry.created_at * 1000).toLocaleString("zh-CN")}</small></div><span className={entry.units > 0 ? "positive" : entry.units < 0 ? "negative" : ""}>{entry.units > 0 ? `+${entry.units}` : entry.units || "确认"}</span></article>
              )) : <div className="small-empty">还没有额度消费记录</div>}
            </section>
          </>
        )}
      </main>
    </Layout>
  );
}

export function AdminUserQuotaPage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<UserQuota[]>([]);
  const [generationValues, setGenerationValues] = useState<Record<string, string>>({});
  const [storageValues, setStorageValues] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const result = await fetchAdminUserQuotas();
    setItems(result.items);
    setStorageValues(Object.fromEntries(result.items.map((item) => [item.user.id, item.unlimited ? "" : (item.storage_limit_bytes / 1024 ** 3).toFixed(0)])));
  }

  useEffect(() => {
    if (authLoading) return;
    if (!user) { navigate(`/login?redirect=${encodeURIComponent("/admin/user-quotas")}`); return; }
    if (user.role !== "admin") { navigate("/"); return; }
    load().catch((nextError) => setError((nextError as Error).message));
  }, [authLoading, user?.id]);

  async function save(item: UserQuota) {
    setBusyId(item.user.id); setError(""); setMessage("");
    try {
      const delta = Number(generationValues[item.user.id] || 0);
      const storage = Number(storageValues[item.user.id] || 0);
      const result = await adjustAdminUserQuota(item.user.id, {
        generation_delta: delta,
        storage_limit_gb: storage,
        detail: "管理员在用户额度页面调整",
      });
      setMessage(`${item.user.email || item.user.username} 的额度已更新`);
      setGenerationValues((current) => ({ ...current, [item.user.id]: "" }));
      setItems((current) => current.map((row) => row.user.id === item.user.id ? result.quota : row));
    } catch (nextError) { setError((nextError as Error).message); }
    finally { setBusyId(""); }
  }

  return (
    <Layout>
      <main className="content-page page-width admin-quota-page">
        <div className="page-heading"><span className="page-icon"><Coins /></span><div><h1>用户额度管理</h1><p>增加或扣减生成次数，并调整每个普通用户的云存储上限。</p></div></div>
        {error && <div className="notice error">{error}</div>}{message && <div className="notice success">{message}</div>}
        <div className="admin-quota-list">
          {items.map((item) => (
            <article key={item.user.id}>
              <div className="admin-quota-user"><strong>{item.user.email || item.user.username}</strong><small>{item.unlimited ? "管理员 · 不限额度" : `剩余 ${item.generation_balance} 次 · 已用 ${formatBytes(item.storage_used_bytes)}`}</small></div>
              {item.unlimited ? <span className="unlimited-badge">不限</span> : <>
                <label><span>次数增减</span><input type="number" min="-10000" max="10000" placeholder="例如 10 或 -2" value={generationValues[item.user.id] || ""} onChange={(event) => setGenerationValues((current) => ({ ...current, [item.user.id]: event.target.value }))} /></label>
                <label><span>存储上限 GB</span><input type="number" min="0" max="10240" value={storageValues[item.user.id] || ""} onChange={(event) => setStorageValues((current) => ({ ...current, [item.user.id]: event.target.value }))} /></label>
                <button type="button" disabled={busyId === item.user.id} onClick={() => void save(item)}>{busyId === item.user.id ? <LoaderCircle className="spin" /> : <Save />}保存</button>
              </>}
            </article>
          ))}
        </div>
      </main>
    </Layout>
  );
}
