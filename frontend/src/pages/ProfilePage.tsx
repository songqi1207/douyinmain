import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  Coins,
  Copy,
  Gift,
  HardDrive,
  History,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { fetchAccountQuota } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import type { QuotaLedgerEntry, UserQuota } from "../types";

const LEDGER_LABELS: Record<QuotaLedgerEntry["event_type"], string> = {
  reserve: "任务预留",
  consume: "视频生成",
  refund: "失败退回",
  adjust: "积分调整",
  invite_reward: "邀请奖励",
  welcome_bonus: "新用户奖励",
};

function formatBytes(value: number) {
  if (value < 0) return "不限";
  if (value < 1024 ** 2) return `${Math.max(0, value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

export function ProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const [quota, setQuota] = useState<UserQuota | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      navigate(`/login?redirect=${encodeURIComponent("/account")}`);
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
      await navigator.clipboard.writeText(inviteUrl);
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
      <main className="content-page page-width profile-page">
        <section className="profile-identity">
          <div className="profile-avatar">{(user?.email || user?.username || "V").slice(0, 1).toUpperCase()}</div>
          <div className="profile-name">
            <span>MY WORKSPACE</span>
            <h1>{user?.username || "创作者"}</h1>
            <p>{user?.email || "未绑定邮箱"} · {user?.role === "admin" ? "管理员" : "创作者账号"}</p>
          </div>
          <span className={`profile-state ${user?.must_change_password ? "warning" : ""}`}>
            <CheckCircle2 />{user?.must_change_password ? "需要修改临时密码" : "账户状态正常"}
          </span>
        </section>

        {error && <div className="notice error">{error}</div>}
        {loading || !quota ? <div className="loading-state"><LoaderCircle className="spin" />正在整理你的工作区</div> : <>
          <section className="profile-dashboard">
            <article className="profile-balance-card">
              <div className="profile-card-label"><Coins />可用积分</div>
              <strong>{quota.unlimited ? "∞" : quota.points_balance.toLocaleString("zh-CN")}</strong>
              <p>{quota.unlimited ? "管理员账户不限制积分" : `${quota.points_reserved.toLocaleString("zh-CN")} 积分正在任务中`}</p>
              <Link to="/account/usage">查看积分明细 <ArrowRight /></Link>
            </article>

            <article className="profile-storage-card">
              <div className="profile-card-label"><HardDrive />视频云空间</div>
              <strong>{formatBytes(quota.storage_used_bytes)}</strong>
              <p>{quota.unlimited ? "空间不限" : `总容量 ${formatBytes(quota.storage_limit_bytes)}`}</p>
              {!quota.unlimited && <><progress max="100" value={storagePercent} /><small>已使用 {storagePercent}%</small></>}
            </article>

            <article className="profile-activity-card">
              <div className="profile-card-label"><History />累计创作消费</div>
              <strong>{quota.points_consumed.toLocaleString("zh-CN")}</strong>
              <p>成功生成后才正式扣除，失败任务自动退回</p>
              <Link to="/records">打开我的作品 <ArrowRight /></Link>
            </article>
          </section>

          <section className="profile-content-grid">
            <div className="profile-main-column">
              <section className="profile-section profile-actions-section">
                <div className="profile-section-heading"><div><span>QUICK START</span><h2>继续你的创作</h2></div></div>
                <div className="profile-action-grid">
                  <Link to="/"><span><Sparkles /></span><div><strong>创建新视频</strong><small>从一个主题开始生成</small></div><ArrowRight /></Link>
                  <Link to="/records"><span><Clock3 /></span><div><strong>我的作品</strong><small>查看进度、播放和下载</small></div><ArrowRight /></Link>
                  <Link to="/account/usage"><span><Coins /></span><div><strong>积分与存储</strong><small>账单、额度与消费规则</small></div><ArrowRight /></Link>
                  <Link to="/account/security"><span><LockKeyhole /></span><div><strong>登录与安全</strong><small>修改密码和保护账号</small></div><ArrowRight /></Link>
                </div>
              </section>

              <section className="profile-section profile-ledger-preview">
                <div className="profile-section-heading"><div><span>RECENT ACTIVITY</span><h2>最近积分变动</h2></div><Link to="/account/usage">查看全部</Link></div>
                {quota.ledger?.length ? quota.ledger.slice(0, 5).map((entry) => <article key={entry.id}>
                  <span className="ledger-icon"><Coins /></span>
                  <div><strong>{LEDGER_LABELS[entry.event_type]}</strong><small>{entry.detail || "积分变动"} · {new Date(entry.created_at * 1000).toLocaleString("zh-CN")}</small></div>
                  <em className={entry.units > 0 ? "positive" : entry.units < 0 ? "negative" : ""}>{entry.units > 0 ? `+${entry.units}` : entry.units || "确认"}</em>
                </article>) : <div className="profile-empty">还没有积分变动，完成第一条视频后会显示在这里。</div>}
              </section>
            </div>

            <aside className="profile-side-column">
              {!quota.unlimited && <section className="profile-invite-card">
                <span className="invite-art"><Gift /></span>
                <div><span>INVITE & EARN</span><h2>邀请好友，一起获得积分</h2></div>
                <p>好友通过你的链接注册并审核成功后，双方各自获得奖励。</p>
                <div className="profile-invite-stats"><div><strong>{quota.invite.invited_count}</strong><small>成功邀请</small></div><div><strong>{quota.invite.rewarded_points}</strong><small>累计奖励</small></div></div>
                <div className="profile-invite-code"><span><small>我的邀请码</small><strong>{quota.invite.code}</strong></span><button type="button" onClick={() => void copyInviteLink()}><Copy />{copied ? "已复制" : "复制链接"}</button></div>
              </section>}
              <section className="profile-account-card">
                <div className="profile-card-label"><UserRound />账户信息</div>
                <dl><div><dt>用户名</dt><dd>{user?.username}</dd></div><div><dt>登录邮箱</dt><dd>{user?.email || "未绑定"}</dd></div><div><dt>账户类型</dt><dd>{user?.role === "admin" ? "管理员" : "普通用户"}</dd></div></dl>
                <Link to="/account/security">管理账户安全 <ArrowRight /></Link>
              </section>
            </aside>
          </section>
        </>}
      </main>
    </Layout>
  );
}
