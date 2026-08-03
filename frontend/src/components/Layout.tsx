import { useEffect, useState } from "react";
import {
  Check,
  ChevronRight,
  Clock3,
  Coins,
  Gauge,
  Headphones,
  HelpCircle,
  Laptop,
  ListVideo,
  Languages,
  LogOut,
  Menu,
  Palette,
  Settings,
  ShieldCheck,
  Sparkles,
  Store,
  UserRound,
  X,
} from "lucide-react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";

import { fetchAccountQuota } from "../api";
import { useAuth } from "../auth";
import { COLOR_THEMES, usePreferences } from "../preferences";
import { JobNotifications } from "./JobNotifications";
import type { UserQuota } from "../types";

const NAV_ITEMS = [
  { to: "/", zh: "创作工作台", en: "Create", icon: Sparkles, end: true },
  { to: "/workflows", zh: "工作流库", en: "Workflows", icon: Store },
  { to: "/voices", zh: "声音工作室", en: "Voice Studio", icon: Headphones },
  { to: "/records", zh: "我的作品", en: "My Creations", icon: Clock3 },
  { to: "/devices", zh: "渲染设备", en: "Render Devices", icon: Laptop, adminOnly: true },
] as const;

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const { theme, language, setTheme, setLanguage, tr, locale } = usePreferences();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [quota, setQuota] = useState<UserQuota | null>(null);

  useEffect(() => {
    if (!user) { setQuota(null); return; }
    fetchAccountQuota().then(({ quota: result }) => setQuota(result)).catch(() => setQuota(null));
  }, [user?.id]);

  async function signOut() {
    await logout();
    setMenuOpen(false);
    navigate("/");
  }

  const pageContext = pathname === "/"
    ? ["CREATE", tr("把一个想法，变成一条完整视频", "Turn one idea into a complete video")]
    : pathname.startsWith("/workflows")
      ? ["WORKFLOWS", tr("查找适合内容方向的创作流程", "Find the right creative workflow for your story")]
      : pathname.startsWith("/voices")
        ? ["VOICE STUDIO", tr("选择声音并完成配音制作", "Choose a voice and create your narration")]
        : pathname.startsWith("/records")
          ? ["MY CREATIONS", tr("管理正在生成和已经完成的作品", "Manage active and completed creations")]
          : pathname.startsWith("/devices")
            ? ["RENDER DEVICES", tr("管理剪映助手和本机渲染能力", "Manage your assistant and local rendering")]
            : pathname.startsWith("/account")
              ? ["MY ACCOUNT", tr("积分、作品、云空间与账户安全", "Credits, creations, storage and account security")]
              : pathname.startsWith("/admin")
                ? ["ADMIN CONSOLE", tr("平台运行与用户管理", "Platform operations and user management")]
                : ["VIDEOLAB", tr("AI 视频创作控制台", "AI video creation console")];

  return (
    <div className="app-shell">
      <aside className={`side-rail ${menuOpen ? "open" : ""}`}>
        <Link className="brand rail-brand" to="/" onClick={() => setMenuOpen(false)}>
          <span className="brand-mark">V</span>
          <span><strong>VIDEOLAB</strong><small>{tr("创作控制台", "CREATOR CONSOLE")}</small></span>
        </Link>
        <div className="rail-section-label">{tr("创作空间", "WORKSPACE")}</div>
        <nav className="topnav" aria-label={tr("主导航", "Main navigation")}>
          {NAV_ITEMS.filter((item) => !("adminOnly" in item) || user?.role === "admin").map((item) => {
            const { to, zh, en, icon: Icon } = item;
            return <NavLink end={"end" in item ? item.end : false} key={to} to={to} onClick={() => setMenuOpen(false)}>
              <Icon size={18} /><span>{tr(zh, en)}</span>
            </NavLink>;
          })}
        </nav>
        {user?.role === "admin" && <div className="rail-admin">
          <div className="rail-section-label">{tr("系统管理", "ADMIN")}</div>
          <NavLink to="/admin/runtime-settings" onClick={() => setMenuOpen(false)}><Settings />{tr("运行配置", "Runtime")}</NavLink>
          <NavLink to="/admin/creations" onClick={() => setMenuOpen(false)}><ListVideo />{tr("全站创作", "All Creations")}</NavLink>
          <NavLink to="/admin/user-quotas" onClick={() => setMenuOpen(false)}><Gauge />{tr("积分计价", "Credits")}</NavLink>
          <NavLink to="/admin/registrations" onClick={() => setMenuOpen(false)}><ShieldCheck />{tr("注册审核", "Registrations")}</NavLink>
        </div>}
        <div className="rail-support">
          {user && <NavLink className="rail-account" to="/account" onClick={() => setMenuOpen(false)}>
            <span className="rail-account-avatar">{(user.email || user.username).slice(0, 1).toUpperCase()}</span>
            <span><strong>{user.username}</strong><small>{quota?.unlimited ? tr("积分不限", "Unlimited credits") : quota ? tr(`${quota.points_balance.toLocaleString(locale)} 积分`, `${quota.points_balance.toLocaleString(locale)} credits`) : tr("个人中心", "Profile")}</small></span>
            <ChevronRight />
          </NavLink>}
          <Link to="/help" onClick={() => setMenuOpen(false)}><HelpCircle />{tr("使用帮助", "Help")}</Link>
          {!user && <p>{tr("登录后可查看个人作品、积分和云存储。", "Sign in to view creations, credits and cloud storage.")}</p>}
        </div>
      </aside>
      {menuOpen && <button className="rail-scrim" type="button" aria-label={tr("关闭导航", "Close navigation")} onClick={() => setMenuOpen(false)} />}
      <div className="shell-stage">
        <header className="topbar">
          <button className="mobile-menu-button" type="button" aria-expanded={menuOpen} aria-label={menuOpen ? tr("关闭导航", "Close navigation") : tr("打开导航", "Open navigation")} onClick={() => setMenuOpen((value) => !value)}>
            {menuOpen ? <X /> : <Menu />}
          </button>
          <Link className="brand mobile-brand" to="/"><span className="brand-mark">V</span><span>VIDEOLAB</span></Link>
          <div className="header-context"><small>VIDEOLAB / {pageContext[0]}</small><strong>{pageContext[1]}</strong></div>
          <div className="preference-control">
            <button className="preference-trigger" type="button" aria-expanded={preferencesOpen} aria-label={tr("外观与语言", "Appearance and language")} onClick={() => setPreferencesOpen((value) => !value)}><Palette /><Languages /></button>
            {preferencesOpen && <div className="preference-popover">
              <div className="preference-title"><span>{tr("界面偏好", "Preferences")}</span><small>{tr("自动保存在当前浏览器", "Saved in this browser")}</small></div>
              <div className="preference-group"><strong>{tr("颜色主题", "Color theme")}</strong><div className="theme-options">
                {COLOR_THEMES.map((item) => <button className={theme === item.id ? "selected" : ""} type="button" key={item.id} onClick={() => setTheme(item.id)}><i data-swatch={item.id} />{tr(item.zh, item.en)}{theme === item.id && <Check />}</button>)}
              </div></div>
              <div className="preference-group"><strong>{tr("界面语言", "Interface language")}</strong><div className="language-options"><button className={language === "zh-CN" ? "selected" : ""} type="button" onClick={() => setLanguage("zh-CN")}>简体中文</button><button className={language === "en" ? "selected" : ""} type="button" onClick={() => setLanguage("en")}>English</button></div></div>
            </div>}
          </div>
          <div className="auth-nav">
            {user ? <>
              <JobNotifications />
              <Link className="points-link" to="/account/usage"><Coins size={15} /><span>{quota?.unlimited ? tr("积分不限", "Unlimited") : quota ? tr(`${quota.points_balance.toLocaleString(locale)} 积分`, `${quota.points_balance.toLocaleString(locale)} credits`) : tr("积分", "Credits")}</span></Link>
              <Link className={user.must_change_password ? "security-alert-link" : "user-link"} to="/account">
                {user.must_change_password ? <ShieldCheck size={15} /> : <span className="user-avatar">{(user.email || user.username).slice(0, 1).toUpperCase()}</span>}
                <span>{user.username}</span>
              </Link>
              <button type="button" onClick={() => void signOut()} aria-label={tr("退出登录", "Sign out")}><LogOut size={15} /><span>{tr("退出", "Sign out")}</span></button>
            </> : <><Link to="/login">{tr("登录", "Sign in")}</Link><Link className="register-link" to="/register">{tr("申请注册", "Request access")}</Link></>}
          </div>
        </header>
        {user?.must_change_password && <div className="security-banner"><ShieldCheck size={17} /><span>{tr("当前使用的是临时密码，请先修改密码后再开始创作。", "You are using a temporary password. Change it before creating.")}</span><Link to="/account/security">{tr("立即修改", "Change now")}</Link></div>}
        <div className="shell-content">{children}</div>
        <footer className="site-footer">
          <span>VIDEOLAB · {tr("AI 视频创作控制台", "AI VIDEO CREATOR")}</span>
          <div><Link to="/account">{tr("个人中心", "Profile")}</Link><Link to="/jianying-export">{tr("手工导出", "Manual export")}</Link><Link to="/help">{tr("使用帮助", "Help")}</Link></div>
        </footer>
      </div>
    </div>
  );
}
