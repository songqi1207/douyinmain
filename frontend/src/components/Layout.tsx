import { useState } from "react";
import {
  Clock3,
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
      <header className="topbar">
        <Link className="brand" to="/" onClick={() => setMenuOpen(false)}>
          <span className="brand-mark"><Sparkles size={18} /></span>
          <span>AI 创作工坊</span>
        </Link>
        <nav className={`topnav ${menuOpen ? "open" : ""}`} aria-label="主导航">
          {NAV_ITEMS.map((item) => {
            const { to, label, icon: Icon } = item;
            return (
            <NavLink
              end={"end" in item ? item.end : false}
              key={to}
              to={to}
              onClick={() => setMenuOpen(false)}
            >
              <Icon size={16} /><span>{label}</span>
            </NavLink>
            );
          })}
          <NavLink className="mobile-only-link" to="/help" onClick={() => setMenuOpen(false)}>
            <HelpCircle size={16} /><span>使用帮助</span>
          </NavLink>
        </nav>
        <div className="auth-nav">
          {user ? (
            <>
              <JobNotifications />
              {user.role === "admin" && <Link to="/admin/runtime-settings"><Settings size={14} />运行配置</Link>}
              {user.role === "admin" && <Link to="/admin/registrations">注册审核</Link>}
              <Link
                className={user.must_change_password ? "security-alert-link" : ""}
                to="/account/security"
              >
                {user.must_change_password && <ShieldCheck size={14} />}
                {user.email || user.username}
              </Link>
              <button type="button" onClick={() => void signOut()} aria-label="退出登录">
                <LogOut size={14} /><span>退出</span>
              </button>
            </>
          ) : (
            <>
              <Link to="/login">登录</Link>
              <Link className="register-link" to="/register">申请注册</Link>
            </>
          )}
        </div>
        <button
          className="mobile-menu-button"
          type="button"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "关闭导航" : "打开导航"}
          onClick={() => setMenuOpen((value) => !value)}
        >
          {menuOpen ? <X /> : <Menu />}
        </button>
      </header>
      {user?.must_change_password && (
        <div className="security-banner">
          <ShieldCheck size={17} />
          <span>当前使用的是临时密码，请先修改密码后再开始创作。</span>
          <Link to="/account/security">立即修改</Link>
        </div>
      )}
      {children}
      <footer className="site-footer">
        <div className="page-width footer-grid">
          <div>
            <Link className="brand footer-brand" to="/">
              <span className="brand-mark"><Sparkles size={16} /></span>
              <span>AI 创作工坊</span>
            </Link>
            <p>从一个主题到可下载视频，把复杂工作流留在后台。</p>
          </div>
          <div>
            <strong>产品</strong>
            <Link to="/">一键创作</Link>
            <Link to="/workflows">工作流商店</Link>
            <Link to="/voices">配音广场</Link>
          </div>
          <div>
            <strong>支持</strong>
            <Link to="/devices">设备中心</Link>
            <Link to="/jianying-export">手工导出</Link>
            <Link to="/help">使用帮助</Link>
          </div>
          <div>
            <strong>相关平台</strong>
            <a href="https://ai.laobaiai.top/" target="_blank" rel="noreferrer">AI 爆款创作平台</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
