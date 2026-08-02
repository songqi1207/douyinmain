import { Check, Gift, LoaderCircle, LockKeyhole, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { login, register } from "../api";
import { useAuth } from "../auth";
import { Layout } from "../components/Layout";
import { usePreferences } from "../preferences";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { setAuth } = useAuth();
  const { tr } = usePreferences();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState(() => searchParams.get("invite") || "");
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
        const result = await register(email, inviteCode);
        setSuccess(result.message);
        setEmail("");
        return;
      }
      const auth = await login(email, password);
      setAuth(auth);
      if (auth.user?.must_change_password) {
        navigate("/account/security");
        return;
      }
      const redirect = searchParams.get("redirect");
      navigate(redirect?.startsWith("/") && !redirect.startsWith("//") ? redirect : "/");
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Layout>
      <main className="auth-page page-width">
        <section className="auth-card upgraded">
          <span className="brand-mark"><Sparkles /></span>
          <span className="eyebrow">{isRegister ? "JOIN THE STUDIO" : "WELCOME BACK"}</span>
          <h1>{isRegister ? tr("申请创作者账号", "Request a creator account") : tr("登录创作工作台", "Sign in to your workspace")}</h1>
          <p>{isRegister ? tr("提交邮箱，审核通过后登录密码会发送到你的邮箱。", "Submit your email and receive a password after approval.") : tr("继续你的创作、设备和视频记录。", "Continue with your creations, devices and video history.")}</p>
          <form onSubmit={(event) => void submit(event)}>
            <label>
              <span>{isRegister ? tr("申请邮箱", "Email") : tr("邮箱 / 用户名", "Email / username")}</span>
              <div className="input-with-icon"><Mail /><input autoComplete="username" type={isRegister ? "email" : "text"} value={email} onChange={(event) => setEmail(event.target.value)} placeholder={isRegister ? "name@example.com" : tr("输入邮箱或用户名", "Enter email or username")} required /></div>
            </label>
            {isRegister && (
              <label>
                <span>{tr("邀请码（选填）", "Invite code (optional)")}</span>
                <div className="input-with-icon"><Gift /><input value={inviteCode} onChange={(event) => setInviteCode(event.target.value.toUpperCase())} placeholder={tr("填写后双方可获得积分", "Both users receive credits after approval")} maxLength={32} /></div>
              </label>
            )}
            {!isRegister && (
              <label>
                <span>{tr("登录密码", "Password")}</span>
                <div className="input-with-icon"><LockKeyhole /><input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={tr("输入登录密码", "Enter your password")} required /></div>
              </label>
            )}
            {error && <div className="notice error">{error}</div>}
            {success && <div className="notice success"><Check />{success}</div>}
            <button className="primary-button" disabled={busy || Boolean(success)} type="submit">{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />}{busy ? tr("正在提交", "Submitting") : isRegister ? tr("提交注册申请", "Submit request") : tr("安全登录", "Sign in securely")}</button>
          </form>
          <div className="auth-switch">{isRegister ? <>{tr("已经收到通过邮件？", "Already approved?")}<Link to="/login">{tr("立即登录", "Sign in")}</Link></> : <>{tr("还没有账号？", "Need an account?")}<Link to="/register">{tr("申请注册", "Request access")}</Link></>}</div>
          <small className="auth-trust"><ShieldCheck />{tr("密码和第三方密钥都不会发送到前端页面", "Passwords and provider keys are never exposed to the client")}</small>
        </section>
      </main>
    </Layout>
  );
}
