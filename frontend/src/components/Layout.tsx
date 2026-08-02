import { useState } from "react";
import {
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
  X,
} from "lucide-react";
import { Link, NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../auth";
import { JobNotifications } from "./JobNotifications";

const NAV_ITEMS = [
  { to: "/", label: "开始创作", icon: Sparkles, end: true },
  { to: "/workflows", label: "工作流", icon: Store },
  { to: "/voices", label: "配音", icon: Headphones },
  { to: "/records", label: "创作记录", icon: Clock3 },
  { to: "/devices", label: "设备", icon: Laptop },
] as const;

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  async function signOut() {
    await logout();
    setMenuOpen(false);
    navigate("/");
  }

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
          <Link to="/help" onClick={() => setMenuOpen(false)}><HelpCircle />使用帮助</Link>
          <p>从灵感到成片，流程都在这里。</p>
        </div>
      </aside>
      {menuOpen && <button className="rail-scrim" type="button" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />}
      <div className="shell-stage">
        <header className="topbar">
          <button className="mobile-menu-button" type="button" aria-expanded={menuOpen} aria-label={menuOpen ? "关闭导航" : "打开导航"} onClick={() => setMenuOpen((value) => !value)}>
            {menuOpen ? <X /> : <Menu />}
          </button>
          <Link className="brand mobile-brand" to="/"><span className="brand-mark">V</span><span>VIDEOLAB</span></Link>
          <div className="header-context"><small>CREATOR OPERATING SYSTEM</small><strong>把一个想法，变成一条完整视频</strong></div>
          <div className="auth-nav">
            {user ? <>
              <JobNotifications />
              <Link className="points-link" to="/account/usage"><Coins size={15} /><span>积分中心</span></Link>
              <Link className={user.must_change_password ? "security-alert-link" : "user-link"} to="/account/security">
                {user.must_change_password ? <ShieldCheck size={15} /> : <span className="user-avatar">{(user.email || user.username).slice(0, 1).toUpperCase()}</span>}
                <span>{user.email || user.username}</span>
              </Link>
              <button type="button" onClick={() => void signOut()} aria-label="退出登录"><LogOut size={15} /><span>退出</span></button>
            </> : <><Link to="/login">登录</Link><Link className="register-link" to="/register">申请注册</Link></>}
          </div>
        </header>
        {user?.must_change_password && <div className="security-banner"><ShieldCheck size={17} /><span>当前使用的是临时密码，请先修改密码后再开始创作。</span><Link to="/account/security">立即修改</Link></div>}
        <div className="shell-content">{children}</div>
        <footer className="site-footer">
          <span>VIDEOLAB · AI 视频创作控制台</span>
          <div><Link to="/jianying-export">手工导出</Link><Link to="/help">使用帮助</Link><a href="https://ai.laobaiai.top/" target="_blank" rel="noreferrer">相关平台</a></div>
        </footer>
      </div>
    </div>
  );
}
