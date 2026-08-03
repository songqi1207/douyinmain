import {
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  Coins,
  Copy,
  Gift,
  HardDrive,
  History,
  LoaderCircle,
  LockKeyhole,
  Languages,
  Palette,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { fetchAccountQuota } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import { COLOR_THEMES, usePreferences } from "../preferences";
import type { QuotaLedgerEntry, UserQuota } from "../types";

const LEDGER_LABELS: Record<string, [string, string]> = {
  reserve: ["任务预留", "Task reservation"],
  consume: ["视频生成", "Video generation"],
  refund: ["失败退回", "Automatic refund"],
  adjust: ["积分调整", "Credit adjustment"],
  invite_reward: ["邀请奖励", "Referral reward"],
  welcome_bonus: ["新用户奖励", "Welcome bonus"],
};

LEDGER_LABELS.storage_reserve = ["云视频保留", "Cloud video retention"];
LEDGER_LABELS.storage_release = ["云视频释放", "Cloud video released"];

function formatBytes(value: number) {
  if (value < 0) return "不限";
  if (value < 1024 ** 2) return `${Math.max(0, value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

export function ProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const { theme, language, setTheme, setLanguage, tr, locale } = usePreferences();
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
            <h1>{user?.username || tr("创作者", "Creator")}</h1>
            <p>{user?.email || tr("未绑定邮箱", "No email linked")} · {user?.role === "admin" ? tr("管理员", "Administrator") : tr("创作者账号", "Creator account")}</p>
          </div>
          <span className={`profile-state ${user?.must_change_password ? "warning" : ""}`}>
            <CheckCircle2 />{user?.must_change_password ? tr("需要修改临时密码", "Temporary password must be changed") : tr("账户状态正常", "Account is secure")}
          </span>
          <Link className="profile-credit-pill" to="/account/usage">
            <Coins />
            <span><small>{tr("我的积分", "My credits")}</small><strong>{loading || !quota ? "…" : quota.unlimited ? "∞" : quota.points_balance.toLocaleString(locale)}</strong></span>
            <ArrowRight />
          </Link>
        </section>

        {error && <div className="notice error">{error}</div>}
        {loading || !quota ? <div className="loading-state"><LoaderCircle className="spin" />{tr("正在整理你的工作区", "Preparing your workspace")}</div> : <>
          <section className="profile-dashboard">
            <article className="profile-balance-card">
              <div className="profile-card-label"><Coins />{tr("可用积分", "Available credits")}</div>
              <strong>{quota.unlimited ? "∞" : quota.points_balance.toLocaleString(locale)}</strong>
              <p>{quota.unlimited ? tr("管理员账户不限制积分", "Unlimited administrator credits") : tr(`${quota.points_reserved.toLocaleString(locale)} 积分正在任务中`, `${quota.points_reserved.toLocaleString(locale)} credits reserved by active tasks`)}</p>
              <Link to="/account/usage">{tr("查看积分明细", "View credit history")} <ArrowRight /></Link>
            </article>

            <article className="profile-storage-card">
              <div className="profile-card-label"><HardDrive />{tr("视频云空间", "Video cloud storage")}</div>
              <strong>{formatBytes(quota.storage_used_bytes)}</strong>
              {!quota.unlimited && <small>{tr(`云端保留占用 ${quota.storage_points_reserved} 积分，删除视频后释放`, `Cloud retention: ${quota.storage_points_reserved} credits reserved (released when deleted)`)}</small>}
              <p>{quota.unlimited ? tr("空间不限", "Unlimited storage") : tr(`总容量 ${formatBytes(quota.storage_limit_bytes)}`, `${formatBytes(quota.storage_limit_bytes)} total`)}</p>
              {!quota.unlimited && <><progress max="100" value={storagePercent} /><small>{tr(`已使用 ${storagePercent}%`, `${storagePercent}% used`)}</small></>}
            </article>

            <article className="profile-activity-card">
              <div className="profile-card-label"><History />{tr("累计创作消费", "Lifetime usage")}</div>
              <div className="profile-deducted-label">{tr("\u5df2\u6263\u9664\u79ef\u5206", "Credits charged")}</div>
              <strong>{quota.points_consumed.toLocaleString(locale)}</strong>
              <p>{tr("成功生成后才正式扣除，失败任务自动退回", "Credits are charged only after success; failed tasks are refunded")}</p>
              <Link to="/records">{tr("打开我的作品", "Open my creations")} <ArrowRight /></Link>
            </article>
          </section>

          <section className="profile-content-grid">
            <div className="profile-main-column">
              <section className="profile-section profile-actions-section">
                <div className="profile-section-heading"><div><span>QUICK START</span><h2>{tr("继续你的创作", "Continue creating")}</h2></div></div>
                <div className="profile-action-grid">
                  <Link to="/"><span><Sparkles /></span><div><strong>{tr("创建新视频", "Create a video")}</strong><small>{tr("从一个主题开始生成", "Start with one topic")}</small></div><ArrowRight /></Link>
                  <Link to="/records"><span><Clock3 /></span><div><strong>{tr("我的作品", "My creations")}</strong><small>{tr("查看进度、播放和下载", "Track, play and download")}</small></div><ArrowRight /></Link>
                  <Link to="/account/usage"><span><Coins /></span><div><strong>{tr("积分与存储", "Credits & storage")}</strong><small>{tr("账单、额度与消费规则", "History, limits and billing")}</small></div><ArrowRight /></Link>
                  <Link to="/account/security"><span><LockKeyhole /></span><div><strong>{tr("登录与安全", "Login & security")}</strong><small>{tr("修改密码和保护账号", "Password and account protection")}</small></div><ArrowRight /></Link>
                </div>
              </section>

              <section className="profile-section profile-ledger-preview">
                <div className="profile-section-heading"><div><span>RECENT ACTIVITY</span><h2>{tr("最近积分变动", "Recent credit activity")}</h2></div><Link to="/account/usage">{tr("查看全部", "View all")}</Link></div>
                {quota.ledger?.length ? quota.ledger.slice(0, 5).map((entry) => <article key={entry.id}>
                  <span className="ledger-icon"><Coins /></span>
                  <div><strong>{tr(...LEDGER_LABELS[entry.event_type])}</strong><small>{entry.detail || tr("积分变动", "Credit activity")} · {new Date(entry.created_at * 1000).toLocaleString(locale)}</small></div>
                  <em className={entry.units > 0 ? "positive" : entry.units < 0 ? "negative" : ""}>{entry.units > 0 ? `+${entry.units}` : entry.units || tr("确认", "Confirmed")}</em>
                </article>) : <div className="profile-empty">{tr("还没有积分变动，完成第一条视频后会显示在这里。", "No credit activity yet. Your first completed video will appear here.")}</div>}
              </section>
            </div>

            <aside className="profile-side-column">
              {!quota.unlimited && <section className="profile-invite-card">
                <span className="invite-art"><Gift /></span>
                <div><span>INVITE & EARN</span><h2>{tr("邀请好友，一起获得积分", "Invite friends and earn credits")}</h2></div>
                <p>{tr("好友通过你的链接注册并审核成功后，双方各自获得奖励。", "When a friend joins through your link and is approved, both of you receive credits.")}</p>
                <div className="profile-invite-stats"><div><strong>{quota.invite.invited_count}</strong><small>{tr("成功邀请", "Successful invites")}</small></div><div><strong>{quota.invite.rewarded_points}</strong><small>{tr("累计奖励", "Credits earned")}</small></div></div>
                <div className="profile-invite-code"><span><small>{tr("我的邀请码", "Invite code")}</small><strong>{quota.invite.code}</strong></span><button type="button" onClick={() => void copyInviteLink()}><Copy />{copied ? tr("已复制", "Copied") : tr("复制链接", "Copy link")}</button></div>
              </section>}
              <section className="profile-preferences-card">
                <div className="profile-card-label"><Palette />{tr("界面偏好", "Interface preferences")}</div>
                <div className="profile-preference-row"><span><Palette />{tr("颜色主题", "Color theme")}</span><div className="profile-theme-options">{COLOR_THEMES.map((item) => <button className={theme === item.id ? "selected" : ""} type="button" title={tr(item.zh, item.en)} aria-label={tr(item.zh, item.en)} key={item.id} onClick={() => setTheme(item.id)}><i data-swatch={item.id} />{theme === item.id && <Check />}</button>)}</div></div>
                <div className="profile-preference-row"><span><Languages />{tr("界面语言", "Language")}</span><div className="language-options"><button className={language === "zh-CN" ? "selected" : ""} type="button" onClick={() => setLanguage("zh-CN")}>中文</button><button className={language === "en" ? "selected" : ""} type="button" onClick={() => setLanguage("en")}>EN</button></div></div>
                <small>{tr("设置会自动保存在当前浏览器。", "Preferences are saved automatically in this browser.")}</small>
              </section>
              <section className="profile-account-card">
                <div className="profile-card-label"><UserRound />{tr("账户信息", "Account information")}</div>
                <dl><div><dt>{tr("用户名", "Username")}</dt><dd>{user?.username}</dd></div><div><dt>{tr("登录邮箱", "Email")}</dt><dd>{user?.email || tr("未绑定", "Not linked")}</dd></div><div><dt>{tr("账户类型", "Role")}</dt><dd>{user?.role === "admin" ? tr("管理员", "Administrator") : tr("普通用户", "Creator")}</dd></div></dl>
                <Link to="/account/security">{tr("管理账户安全", "Manage account security")} <ArrowRight /></Link>
              </section>
            </aside>
          </section>
        </>}
      </main>
    </Layout>
  );
}
