import { useEffect, useState } from "react";
import {
  ChevronRight,
  Clock3,
  Coins,
  Gauge,
  Headphones,
  HelpCircle,
  Laptop,
  LogOut,
  Menu,
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
import { JobNotifications } from "./JobNotifications";
import type { UserQuota } from "../types";

const NAV_ITEMS = [
  { to: "/", label: "创作工作台", icon: Sparkles, end: true },
  { to: "/workflows", label: "工作流库", icon: Store },
  { to: "/voices", label: "声音工作室", icon: Headphones },
  { to: "/records", label: "我的作品", icon: Clock3 },
  { to: "/devices", label: "渲染设备", icon: Laptop },
] as const;

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
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
    ? ["CREATE", "把一个想法，变成一条完整视频"]
    : pathname.startsWith("/workflows")
      ? ["WORKFLOWS", "查找适合内容方向的创作流程"]
      : pathname.startsWith("/voices")
        ? ["VOICE STUDIO", "选择声音并完成配音制作"]
        : pathname.startsWith("/records")
          ? ["MY CREATIONS", "管理正在生成和已经完成的作品"]
          : pathname.startsWith("/devices")
            ? ["RENDER DEVICES", "管理剪映助手和本机渲染能力"]
            : pathname.startsWith("/account")
              ? ["MY ACCOUNT", "积分、作品、云空间与账户安全"]
              : pathname.startsWith("/admin")
                ? ["ADMIN CONSOLE", "平台运行与用户管理"]
                : ["VIDEOLAB", "AI 视频创作控制台"];

  return (
    <div className="app-shell">
      <aside className={`side-rail ${menuOpen ? "open" : ""}`}>
        <Link className="brand rail-brand" to="/" onClick={() => setMenuOpen(false)}>
          <span className="brand-mark">V</span>
          <span><strong>VIDEOLAB</strong><small>创作控制台</small></span>
        </Link>
        <div className="rail-section-label">创作空间</div>
        <nav className="topnav" aria-label="主导航">
          {NAV_ITEMS.map((item) => {
            const { to, label, icon: Icon } = item;
            return <NavLink end={"end" in item ? item.end : false} key={to} to={to} onClick={() => setMenuOpen(false)}>
              <Icon size={18} /><span>{label}</span>
            </NavLink>;
          })}
        </nav>
        {user?.role === "admin" && <div className="rail-admin">
          <div className="rail-section-label">系统管理</div>
          <NavLink to="/admin/runtime-settings" onClick={() => setMenuOpen(false)}><Settings />运行配置</NavLink>
          <NavLink to="/admin/user-quotas" onClick={() => setMenuOpen(false)}><Gauge />积分计价</NavLink>
          <NavLink to="/admin/registrations" onClick={() => setMenuOpen(false)}><ShieldCheck />注册审核</NavLink>
        </div>}
        <div className="rail-support">
          {user && <NavLink className="rail-account" to="/account" onClick={() => setMenuOpen(false)}>
            <span className="rail-account-avatar">{(user.email || user.username).slice(0, 1).toUpperCase()}</span>
            <span><strong>{user.username}</strong><small>{quota?.unlimited ? "积分不限" : quota ? `${quota.points_balance.toLocaleString("zh-CN")} 积分` : "个人中心"}</small></span>
            <ChevronRight />
          </NavLink>}
          <Link to="/help" onClick={() => setMenuOpen(false)}><HelpCircle />使用帮助</Link>
          {!user && <p>登录后可查看个人作品、积分和云存储。</p>}
        </div>
      </aside>
      {menuOpen && <button className="rail-scrim" type="button" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />}
      <div className="shell-stage">
        <header className="topbar">
          <button className="mobile-menu-button" type="button" aria-expanded={menuOpen} aria-label={menuOpen ? "关闭导航" : "打开导航"} onClick={() => setMenuOpen((value) => !value)}>
            {menuOpen ? <X /> : <Menu />}
          </button>
          <Link className="brand mobile-brand" to="/"><span className="brand-mark">V</span><span>VIDEOLAB</span></Link>
          <div className="header-context"><small>VIDEOLAB / {pageContext[0]}</small><strong>{pageContext[1]}</strong></div>
          <div className="auth-nav">
            {user ? <>
              <JobNotifications />
              <Link className="points-link" to="/account/usage"><Coins size={15} /><span>{quota?.unlimited ? "积分不限" : quota ? `${quota.points_balance.toLocaleString("zh-CN")} 积分` : "积分"}</span></Link>
              <Link className={user.must_change_password ? "security-alert-link" : "user-link"} to="/account">
                {user.must_change_password ? <ShieldCheck size={15} /> : <span className="user-avatar">{(user.email || user.username).slice(0, 1).toUpperCase()}</span>}
                <span>{user.username}</span>
              </Link>
              <button type="button" onClick={() => void signOut()} aria-label="退出登录"><LogOut size={15} /><span>退出</span></button>
            </> : <><Link to="/login">登录</Link><Link className="register-link" to="/register">申请注册</Link></>}
          </div>
        </header>
        {user?.must_change_password && <div className="security-banner"><ShieldCheck size={17} /><span>当前使用的是临时密码，请先修改密码后再开始创作。</span><Link to="/account/security">立即修改</Link></div>}
        <div className="shell-content">{children}</div>
        <footer className="site-footer">
          <span>VIDEOLAB · AI 视频创作控制台</span>
          <div><Link to="/account">个人中心</Link><Link to="/jianying-export">手工导出</Link><Link to="/help">使用帮助</Link></div>
        </footer>
      </div>
    </div>
  );
}
