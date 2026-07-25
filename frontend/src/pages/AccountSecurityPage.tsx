import { Check, KeyRound, LoaderCircle, ShieldCheck } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, changePassword } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";

export function AccountSecurityPage() {
  const { user, loading, setAuth } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (!loading && !user) navigate(`/login?redirect=${encodeURIComponent("/account/security")}`);
  }, [loading, user?.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await changePassword(currentPassword, newPassword);
      setAuth(next);
      setSuccess(true);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (nextError) {
      setError((nextError as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Layout>
      <main className="content-page page-width security-page">
        <div className="page-heading">
          <span className="page-icon"><ShieldCheck /></span>
          <div><h1>账号与安全</h1><p>管理登录密码，保护你的工作流和创作记录。</p></div>
        </div>
        <div className="security-layout">
          <section className="account-summary-card">
            <span className="account-avatar">{(user?.email || user?.username || "A").slice(0, 1).toUpperCase()}</span>
            <div><strong>{user?.email || user?.username}</strong><small>{user?.role === "admin" ? "管理员账号" : "创作者账号"}</small></div>
            <span className={`account-security-state ${user?.must_change_password ? "warning" : ""}`}>
              {user?.must_change_password ? "需要修改临时密码" : "账号状态正常"}
            </span>
          </section>
          <section className="password-card">
            <div className="section-title"><span>修改登录密码</span><KeyRound /></div>
            {user?.must_change_password && <div className="notice warning">这是首次登录。修改邮件中的临时密码后，才能开始创作和配对设备。</div>}
            {success ? (
              <div className="password-success">
                <span><Check /></span>
                <h2>密码修改成功</h2>
                <p>所有旧会话已经失效，当前浏览器已自动换成新的安全会话。</p>
                <Link className="primary-button" to="/">返回创作工作台</Link>
              </div>
            ) : (
              <form onSubmit={(event) => void submit(event)}>
                <label><span>当前密码</span><input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label>
                <label><span>新密码</span><input type="password" minLength={8} maxLength={128} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required /><small>8–128 个字符，不能与当前密码相同</small></label>
                <label><span>确认新密码</span><input type="password" minLength={8} maxLength={128} autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required /></label>
                {error && <div className="notice error">{error}</div>}
                <button className="primary-button" disabled={busy} type="submit">{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />}{busy ? "正在更新" : "安全更新密码"}</button>
              </form>
            )}
          </section>
        </div>
      </main>
    </Layout>
  );
}
