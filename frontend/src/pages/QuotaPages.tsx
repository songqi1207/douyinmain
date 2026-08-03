import { Cloud, Coins, Copy, Eye, Gift, HardDrive, History, KeyRound, LoaderCircle, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { adjustAdminUserQuota, fetchAccountQuota, fetchAdminUserQuotas, fetchAdminWorkflowPricing, resetAdminUserPassword, revealAdminUserPassword, updateAdminWorkflowPricing } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";
import type { AdminWorkflowPricing, QuotaLedgerEntry, UserQuota } from "../types";

function formatBytes(value: number) {
  if (value < 0) return "不限";
  if (value < 1024 * 1024) return `${Math.max(0, value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const LEDGER_LABELS: Record<string, string> = {
  reserve: "创建任务，冻结积分",
  consume: "生成成功，确认扣分",
  refund: "任务失败，自动退分",
  adjust: "管理员调整积分",
  invite_reward: "邀请好友奖励",
  welcome_bonus: "受邀注册奖励",
};

LEDGER_LABELS.storage_reserve = "云视频保留占用";
LEDGER_LABELS.storage_release = "删除云视频释放";

export function AccountUsagePage() {
  const { user, loading: authLoading } = useAuth();
  const { tr, locale } = usePreferences();
  const navigate = useNavigate();
  const [quota, setQuota] = useState<UserQuota | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

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
  const inviteUrl = quota?.invite?.code
    ? `${window.location.origin}/business/register?invite=${encodeURIComponent(quota.invite.code)}`
    : "";

  async function copyInviteLink() {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(inviteUrl);
      else throw new Error("clipboard unavailable");
    } catch {
      const input = document.createElement("textarea");
      input.value = inviteUrl;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <Layout>
      <main className="content-page page-width usage-page">
        <div className="page-heading"><span className="page-icon"><Cloud /></span><div><h1>{tr("积分与云存储", "Credits & Cloud Storage")}</h1><p>{tr("查看平台积分、供应商成本计价、邀请奖励和云端空间。", "Review credits, referral rewards, billing activity and cloud storage.")}</p></div></div>
        {error && <div className="notice error">{error}</div>}
        {loading || !quota ? <div className="loading-state"><LoaderCircle className="spin" />{tr("正在读取额度", "Loading account limits")}</div> : (
          <>
            <section className="quota-overview-grid">
              {!quota.unlimited && <article className="quota-storage-points-card"><span><Coins /></span><div><small>Cloud video retention</small><strong>{quota.storage_points_reserved} credits reserved</strong><p>Charged by 100 MB and released when you delete the video.</p></div></article>}
              <article><span><Coins /></span><div><small>{tr("可用平台积分", "Available credits")}</small><strong>{quota.unlimited ? tr("不限", "Unlimited") : tr(`${quota.points_balance} 分`, `${quota.points_balance} credits`)}</strong><p>{quota.points_reserved ? tr(`${quota.points_reserved} 分正在任务中`, `${quota.points_reserved} credits reserved`) : tr("当前没有冻结积分", "No reserved credits")}</p></div></article>
              <article><span><HardDrive /></span><div><small>{tr("视频云存储", "Video cloud storage")}</small><strong>{formatBytes(quota.storage_used_bytes)} / {formatBytes(quota.storage_limit_bytes)}</strong><p>{quota.unlimited ? tr("管理员账号不限制空间", "Unlimited administrator storage") : tr(`剩余 ${formatBytes(quota.storage_available_bytes)}`, `${formatBytes(quota.storage_available_bytes)} available`)}</p></div></article>
              <article className={quota.can_generate ? "ready" : "blocked"}><span><ShieldCheck /></span><div><small>{tr("创作状态", "Creation status")}</small><strong>{quota.can_generate ? tr("可以生成视频", "Ready to generate") : tr("积分或存储不足", "Insufficient credits or storage")}</strong><p>{quota.can_generate ? tr("每个工作流按实际配置价格扣分", "Each workflow uses its configured credit price") : tr("请邀请好友、充值积分或释放存储", "Invite friends, add credits or free storage")}</p></div></article>
            </section>
            {!quota.unlimited && <div className="storage-meter"><div><span>云存储使用率</span><strong>{storagePercent}%</strong></div><progress max="100" value={storagePercent} /></div>}
            {!quota.unlimited && <section className="invite-reward-card">
              <span><Gift /></span><div><h2>{tr("邀请好友送积分", "Invite friends and earn credits")}</h2><p>{tr(`好友使用邀请码注册并通过审核后，你获得 ${quota.invite.inviter_reward_points} 积分，好友获得 ${quota.invite.invitee_reward_points} 积分。`, `After an invited friend is approved, you earn ${quota.invite.inviter_reward_points} credits and they earn ${quota.invite.invitee_reward_points} credits.`)}</p><small>{tr(`已成功邀请 ${quota.invite.invited_count} 人，累计奖励 ${quota.invite.rewarded_points} 积分`, `${quota.invite.invited_count} successful invites · ${quota.invite.rewarded_points} credits earned`)}</small></div>
              <div className="invite-code-box"><strong>{quota.invite.code}</strong><button type="button" onClick={() => void copyInviteLink()}><Copy />{copied ? "已复制" : "复制邀请链接"}</button></div>
            </section>}
            <section className="quota-rules-card">
              <h2>消费规则</h2>
              <ol><li>每个工作流按照内容与素材生成服务的计费成本核算积分。</li><li>用户售价 = 工作流成本 × {quota.billing_multiplier}，创建任务时先冻结对应积分。</li><li>视频成功后正式扣分；任务失败自动退回全部冻结积分。</li><li>网页预览版和高清下载版计入云存储，删除视频后立即释放空间。</li></ol>
            </section>
            <section className="quota-ledger-card">
              <div className="section-title"><span>{tr("积分明细", "Credit history")}</span><History /></div>
              {quota.ledger?.length ? quota.ledger.map((entry) => (
                <article key={entry.id}><div><strong>{LEDGER_LABELS[entry.event_type]}</strong><small>{entry.detail || tr("积分变动", "Credit activity")} · {new Date(entry.created_at * 1000).toLocaleString(locale)}</small></div><span className={entry.units > 0 ? "positive" : entry.units < 0 ? "negative" : ""}>{entry.units > 0 ? `+${entry.units}` : entry.units || tr("确认", "Confirmed")}</span></article>
              )) : <div className="small-empty">还没有积分消费记录</div>}
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
  const [pricingItems, setPricingItems] = useState<AdminWorkflowPricing[]>([]);
  const [pricingValues, setPricingValues] = useState<Record<string, { coze: string; mihe: string }>>({});
  const [adminPassword, setAdminPassword] = useState("");
  const [revealedPasswords, setRevealedPasswords] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    const [quotaResult, pricingResult] = await Promise.all([fetchAdminUserQuotas(), fetchAdminWorkflowPricing()]);
    setItems(quotaResult.items);
    setStorageValues(Object.fromEntries(quotaResult.items.map((item) => [item.user.id, item.unlimited ? "" : (item.storage_limit_bytes / 1024 ** 3).toFixed(0)])));
    setPricingItems(pricingResult.items);
    setPricingValues(Object.fromEntries(pricingResult.items.map((item) => [item.workflow.code, { coze: String(item.pricing.coze_cost_points), mihe: String(item.pricing.mihe_cost_points) }])));
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
        points_delta: delta,
        storage_limit_gb: storage,
        detail: "管理员在用户积分页面调整",
      });
      setMessage(`${item.user.email || item.user.username} 的积分与存储额度已更新`);
      setGenerationValues((current) => ({ ...current, [item.user.id]: "" }));
      setItems((current) => current.map((row) => row.user.id === item.user.id ? result.quota : row));
    } catch (nextError) { setError((nextError as Error).message); }
    finally { setBusyId(""); }
  }

  async function savePricing(item: AdminWorkflowPricing) {
    const code = item.workflow.code;
    const values = pricingValues[code] || { coze: "0", mihe: "0" };
    setBusyId(`pricing-${code}`); setError(""); setMessage("");
    try {
      const result = await updateAdminWorkflowPricing(code, {
        coze_cost_points: Number(values.coze || 0),
        mihe_cost_points: Number(values.mihe || 0),
      });
      setPricingItems((current) => current.map((row) => row.workflow.code === code ? { ...row, pricing: result.pricing } : row));
      setMessage(`${item.workflow.name} 的售价已更新为 ${result.pricing.price_points} 积分`);
    } catch (nextError) { setError((nextError as Error).message); }
    finally { setBusyId(""); }
  }

  async function managePassword(item: UserQuota, action: "reveal" | "reset") {
    if (!adminPassword) {
      setError("请先输入当前管理员密码进行二次验证");
      return;
    }
    const busyKey = `password-${action}-${item.user.id}`;
    setBusyId(busyKey); setError(""); setMessage("");
    try {
      const result = action === "reveal"
        ? await revealAdminUserPassword(item.user.id, adminPassword)
        : await resetAdminUserPassword(item.user.id, adminPassword);
      setRevealedPasswords((current) => ({ ...current, [item.user.id]: result.password }));
      setMessage(action === "reveal"
        ? `${item.user.email || item.user.username} 的密码已读取并记录审计日志`
        : `${item.user.email || item.user.username} 的密码已重置，旧登录会话已退出`);
    } catch (nextError) { setError((nextError as Error).message); }
    finally { setBusyId(""); }
  }

  async function copyPassword(userId: string) {
    const password = revealedPasswords[userId] || "";
    if (!password) return;
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(password);
    else {
      const input = document.createElement("textarea");
      input.value = password;
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    setMessage("密码已复制到剪贴板");
  }

  return (
    <Layout>
      <main className="content-page page-width admin-quota-page">
        <div className="page-heading"><span className="page-icon"><Coins /></span><div><h1>积分与成本管理</h1><p>调整用户积分、云存储上限，以及每个工作流的供应商成本。</p></div></div>
        {error && <div className="notice error">{error}</div>}{message && <div className="notice success">{message}</div>}
        <section className="admin-password-auth">
          <div><strong>用户密码保险库</strong><small>查看或重置普通用户密码前，需要输入当前管理员密码。每次操作都会记录管理员、用户、时间和来源 IP。</small></div>
          <label><span>当前管理员密码</span><input type="password" autoComplete="current-password" value={adminPassword} onChange={(event) => setAdminPassword(event.target.value)} placeholder="仅用于本次二次验证" /></label>
        </section>
        <div className="admin-quota-list">
          {items.map((item) => (
            <article key={item.user.id}>
              <div className="admin-quota-user"><strong>{item.user.email || item.user.username}</strong><small>{item.unlimited ? "管理员 · 不限积分" : `剩余 ${item.points_balance} 积分 · 已用 ${formatBytes(item.storage_used_bytes)}`}</small></div>
              {item.unlimited ? <span className="unlimited-badge">不限</span> : <>
                <label><span>积分增减</span><input type="number" min="-10000" max="10000" placeholder="例如 100 或 -20" value={generationValues[item.user.id] || ""} onChange={(event) => setGenerationValues((current) => ({ ...current, [item.user.id]: event.target.value }))} /></label>
                <label><span>存储上限 GB</span><input type="number" min="0" max="10240" value={storageValues[item.user.id] || ""} onChange={(event) => setStorageValues((current) => ({ ...current, [item.user.id]: event.target.value }))} /></label>
                <button type="button" disabled={busyId === item.user.id} onClick={() => void save(item)}>{busyId === item.user.id ? <LoaderCircle className="spin" /> : <Save />}保存</button>
                <div className="admin-password-actions">
                  <button type="button" disabled={busyId.startsWith("password-")} onClick={() => void managePassword(item, "reveal")}>{busyId === `password-reveal-${item.user.id}` ? <LoaderCircle className="spin" /> : <Eye />}查看密码</button>
                  <button type="button" disabled={busyId.startsWith("password-")} onClick={() => void managePassword(item, "reset")}>{busyId === `password-reset-${item.user.id}` ? <LoaderCircle className="spin" /> : <KeyRound />}重置并生成密码</button>
                  {revealedPasswords[item.user.id] && <div className="revealed-password"><span>当前密码</span><code>{revealedPasswords[item.user.id]}</code><button type="button" onClick={() => void copyPassword(item.user.id)}><Copy />复制</button></div>}
                </div>
              </>}
            </article>
          ))}
        </div>
        <section className="workflow-pricing-section">
          <div className="section-title"><span>工作流供应商成本</span><small>售价 =（内容生成额度 + 素材生成积分）× 2</small></div>
          <div className="workflow-pricing-list">
            {pricingItems.map((item) => {
              const values = pricingValues[item.workflow.code] || { coze: "0", mihe: "0" };
              const price = (Number(values.coze || 0) + Number(values.mihe || 0)) * item.pricing.billing_multiplier;
              return <article key={item.workflow.code}>
                <div><strong>{item.workflow.name}</strong><small>{item.workflow.code} · {item.workflow.status === "online" ? "已上线" : "接入中"}</small></div>
                <label><span>内容生成额度</span><input type="number" min="0" max="1000000" value={values.coze} onChange={(event) => setPricingValues((current) => ({ ...current, [item.workflow.code]: { ...values, coze: event.target.value } }))} /></label>
                <label><span>素材生成积分</span><input type="number" min="0" max="1000000" value={values.mihe} onChange={(event) => setPricingValues((current) => ({ ...current, [item.workflow.code]: { ...values, mihe: event.target.value } }))} /></label>
                <div className="workflow-price-total"><small>用户售价</small><strong>{price} 积分</strong></div>
                <button type="button" disabled={busyId === `pricing-${item.workflow.code}`} onClick={() => void savePricing(item)}>{busyId === `pricing-${item.workflow.code}` ? <LoaderCircle className="spin" /> : <Save />}保存价格</button>
              </article>;
            })}
          </div>
        </section>
      </main>
    </Layout>
  );
}
